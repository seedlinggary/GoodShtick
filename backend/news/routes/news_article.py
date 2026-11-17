import os

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from config import db
from security import admin_required, token_required, token_optional
from upload import upload_file
from backend.news.modals.news import NewsArticle, NewsArticleLike, CATEGORIES, MAX_CATEGORIES, normalize_categories, slugify
from backend.news.schemas.news import NewsArticleCardSchema, make_article_schema

# GutKol's own domain (gutkol.com) -- distinct from the generic
# FRONTEND_URL/MAIN_SITE_URL env vars the main site and other modules use,
# since this link has to land on the HOST that actually serves news/routes.js
# (siteMode.js resolves which site renders purely by hostname), not on
# whatever the main consumer site's own domain happens to be.
NEWS_SITE_URL = os.environ.get('NEWS_SITE_URL', 'https://gutkol.com')

# GutKol is now open to the public (the old pre-launch soft lock -- every
# route here required super_admin, including plain reads -- has been lifted
# now that the site is launching for real). Reads are @token_optional
# (public), writing a post is @token_required (any signed-in member, bot
# accounts included), and moderating the scraped/guest queue is
# @admin_required.
news_article_api = Blueprint('news_article_api', __name__, url_prefix='/news')

PAGE_SIZE = 24
TITLE_MAX = 200
BODY_MAX = 8000
EXCERPT_MAX = 500


def _feed_options():
    return [selectinload(NewsArticle.likes)]


def _can_manage(article, user):
    if not user:
        return False
    if user.is_boss:
        return True
    return article.created_by == user.public_id


def _unique_slug(title):
    base = slugify(title)
    rows = {row[0] for row in db.session.query(NewsArticle.slug).filter(NewsArticle.slug.like(f'{base}%')).all()}
    if base not in rows:
        return base
    n = 2
    while f'{base}-{n}' in rows:
        n += 1
    return f'{base}-{n}'


def _public_filter(query):
    """A logged-in user's own post and a scraped article both already set
    approved_to_publish=True explicitly at creation (see create_article/
    news_scraper.py) -- so this can just check that one flag unconditionally
    now. (Before guest posting existed, this checked `imported.is_(False)`
    as an OR-branch instead, trusting every non-scraped post by default --
    that would have let a GUEST submission's pending approved_to_publish=None
    row through too, since imported=False is true for guest posts as well --
    fixed now that reads are public, not just in theory.)"""
    return query.filter(NewsArticle.approved_to_publish.is_(True))


@news_article_api.route('/categories', methods=['GET'])
@token_optional
def list_categories(current_user):
    """The preset list PLUS any custom category a poster has already typed
    in (see create_article/edit_article) -- so a custom topic, once used,
    shows up as a real filter option for everyone else too, not just a
    one-off string only its own author can find again. `presets` is kept
    separate so the frontend can group/label them differently from the
    free-typed ones. Flattened in Python rather than a SQL unnest -- same
    "fine at this app's scale" reasoning as the rest of this module's own
    lean queries (see _public_filter's docstring)."""
    rows = db.session.query(NewsArticle.categories).filter(NewsArticle.categories.isnot(None)).all()
    custom = sorted({c for (cats,) in rows for c in (cats or []) if c and c not in CATEGORIES})
    return jsonify({'categories': list(CATEGORIES) + custom, 'presets': list(CATEGORIES), 'max_categories': MAX_CATEGORIES})


@news_article_api.route('/stats', methods=['GET'])
@token_optional
def news_stats(current_user):
    # Reuses _public_filter (not news_stats' own hand-rolled filter) so this
    # can't drift back out of sync with what list_articles/the feed actually
    # shows -- the old version here checked `imported.is_(False) OR
    # approved_to_publish.is_(True)`, the exact bug _public_filter's own
    # docstring describes (it let a still-pending GUEST post's category
    # count toward totals a visitor never actually sees).
    rows = _public_filter(NewsArticle.query).with_entities(NewsArticle.categories).all()
    total = len(rows)
    by_category = {}
    for (cats,) in rows:
        for c in (cats or []):
            by_category[c] = by_category.get(c, 0) + 1
    contributors = (db.session.query(func.count(func.distinct(NewsArticle.created_by)))
                    .filter(NewsArticle.created_by.isnot(None), NewsArticle.imported.is_(False)).scalar() or 0)
    return jsonify({'articles': total, 'contributors': contributors, 'by_category': by_category})


@news_article_api.route('/sitemap-data', methods=['GET'])
def sitemap_data():
    """Minimal {slug, updated} rows for every publicly-visible article --
    same lean-query pattern as the other sites' own sitemap_data() (see
    torah_post.py's posts_sitemap_data for the convention this mirrors)."""
    rows = _public_filter(db.session.query(NewsArticle.slug, NewsArticle.pub_date)).all()
    return jsonify({
        'articles': [{'slug': slug, 'updated': pub_date.isoformat() if pub_date else None} for slug, pub_date in rows],
    })


@news_article_api.route('/articles', methods=['GET'])
@token_optional
def list_articles(current_user):
    category = (request.args.get('category') or '').strip().lower()
    q = (request.args.get('q') or '').strip()
    source = (request.args.get('source') or '').strip().lower()  # 'original' | 'aggregated'
    sort = (request.args.get('sort') or 'newest').strip().lower()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    query = _public_filter(NewsArticle.query.options(*_feed_options()))
    if category:
        query = query.filter(NewsArticle.categories.contains([category]))
    if source == 'original':
        query = query.filter(NewsArticle.imported.is_(False))
    elif source == 'aggregated':
        query = query.filter(NewsArticle.imported.is_(True))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(NewsArticle.title.ilike(like), NewsArticle.excerpt.ilike(like)))

    total = query.count()
    if sort == 'random':
        query = query.order_by(func.random())
    elif sort == 'alpha':
        query = query.order_by(NewsArticle.title.asc())
    else:
        query = query.order_by(NewsArticle.pub_date.desc())

    rows = query.limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE).all()
    has_more = len(rows) > PAGE_SIZE
    articles = rows[:PAGE_SIZE]

    return jsonify({'articles': NewsArticleCardSchema(many=True).dump(articles), 'page': page, 'has_more': has_more, 'total': total})


@news_article_api.route('/articles/<identifier>', methods=['GET'])
@token_optional
def get_article(current_user, identifier):
    query = NewsArticle.query.options(*_feed_options())
    article = query.filter_by(id=int(identifier)).first() if identifier.isdigit() else query.filter_by(slug=identifier).first()
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    # A pending/rejected scraped article is only visible to an admin
    # reviewing it, never to the public via direct link.
    if article.imported and article.approved_to_publish is not True and not (current_user and current_user.is_boss):
        return jsonify({'message': 'Article not found'}), 404
    article.views_count = (article.views_count or 0) + 1
    db.session.commit()
    return jsonify(make_article_schema(current_user).dump(article))


@news_article_api.route('/articles', methods=['POST'])
@token_required
def create_article(current_user):
    """User-submitted original post -- always imported=False, published
    immediately (see NewsArticle's docstring). Scraped articles are created
    exclusively by news_scraper.py, never through this endpoint.

    Unlike a guest tip, excerpt/body_text/categories are all REQUIRED here --
    the owner explicitly wants every self-authored article (including from
    a bot account set up to auto-generate content) to always carry both a
    short snippet/headline AND the full piece, plus at least one category
    pick (up to MAX_CATEGORIES), never just a bare title."""
    body = request.get_json() or {}
    title = (body.get('title') or '').strip()
    if not title:
        return jsonify({'message': 'Title is required'}), 400
    if len(title) > TITLE_MAX:
        return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400

    excerpt = (body.get('excerpt') or '').strip()
    if not excerpt:
        return jsonify({'message': 'A short snippet/headline (excerpt) is required'}), 400
    if len(excerpt) > EXCERPT_MAX:
        return jsonify({'message': f'Excerpt must be {EXCERPT_MAX} characters or fewer'}), 400
    body_text = (body.get('body_text') or '').strip()
    if not body_text:
        return jsonify({'message': 'The full article text (body_text) is required'}), 400
    if len(body_text) > BODY_MAX:
        return jsonify({'message': f'Body must be {BODY_MAX} characters or fewer'}), 400
    categories = normalize_categories(body.get('categories'))
    if not categories:
        return jsonify({'message': 'At least one category is required'}), 400
    source_url = (body.get('source_url') or '').strip()

    article = NewsArticle(
        slug=_unique_slug(title), title=title, created_by=current_user.public_id,
        excerpt=excerpt or None, body_text=body_text or None, categories=categories,
        image=body.get('image') or None, source_url=source_url or None,
        imported=False, approved_to_publish=True,
    )
    db.session.add(article)
    db.session.commit()
    return jsonify(make_article_schema(current_user).dump(article)), 201


GUEST_EMAIL_MAX = 150
GUEST_PHONE_MAX = 40


# ── Guest (no-account) article routes ───────────────────────────────────────
# "Post without an account" -- anyone can submit a news tip with just an
# email or phone, no login required at all (these 4 routes carry no
# decorator, by design). Always lands pending (approved_to_publish=None),
# unlike create_article's own logged-in posts, which still auto-publish --
# a GUEST byline has nothing vouching for it the way a real account's does,
# so it needs a human (@admin_required) to approve it before anyone sees it.
@news_article_api.route('/articles/guest', methods=['POST'])
def create_guest_article():
    body = request.get_json() or {}
    title = (body.get('title') or '').strip()
    if not title:
        return jsonify({'message': 'Title is required'}), 400
    if len(title) > TITLE_MAX:
        return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400

    excerpt = (body.get('excerpt') or '').strip()
    if len(excerpt) > EXCERPT_MAX:
        return jsonify({'message': f'Excerpt must be {EXCERPT_MAX} characters or fewer'}), 400
    body_text = (body.get('body_text') or '').strip()
    if len(body_text) > BODY_MAX:
        return jsonify({'message': f'Body must be {BODY_MAX} characters or fewer'}), 400
    categories = normalize_categories(body.get('categories')) or ['other']
    source_url = (body.get('source_url') or '').strip()

    guest_email = (body.get('guest_email') or '').strip()[:GUEST_EMAIL_MAX]
    guest_phone = (body.get('guest_phone') or '').strip()[:GUEST_PHONE_MAX]
    if not (guest_email or guest_phone):
        return jsonify({'message': 'At least one of guest_email or guest_phone is required'}), 400

    from backend.guest.modals.guest_throttle import check_and_record_guest_submission
    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many submissions from this network today -- please try again tomorrow.'}), 429

    import secrets
    article = NewsArticle(
        slug=_unique_slug(title), title=title, created_by=None,
        excerpt=excerpt or None, body_text=body_text or None, categories=categories,
        image=body.get('image') or None, source_url=source_url or None,
        imported=False, approved_to_publish=None,
        guest_email=guest_email or None, guest_phone=guest_phone or None,
        guest_manage_token=secrets.token_urlsafe(32),
    )
    db.session.add(article)
    db.session.commit()

    if guest_email:
        try:
            from backend.alerts import emails
            emails.send_guest_submission_email(
                guest_email, 'your news submission', article.title,
                f'{NEWS_SITE_URL}/guest/news/{article.guest_manage_token}',
            )
        except Exception:
            pass  # an email failure should never break the actual submission

    data = make_article_schema(None).dump(article)
    data['guest_manage_token'] = article.guest_manage_token
    return jsonify(data), 201


@news_article_api.route('/articles/guest/<token>', methods=['GET'])
def get_guest_article(token):
    article = NewsArticle.query.filter_by(guest_manage_token=token).first()
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    return jsonify(make_article_schema(None).dump(article))


@news_article_api.route('/articles/guest/<token>', methods=['PATCH'])
def edit_guest_article(token):
    article = NewsArticle.query.filter_by(guest_manage_token=token).first()
    if not article:
        return jsonify({'message': 'Article not found'}), 404

    body = request.get_json() or {}
    if 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return jsonify({'message': 'Title is required'}), 400
        if len(title) > TITLE_MAX:
            return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400
        article.title = title
    if 'excerpt' in body:
        excerpt = (body.get('excerpt') or '').strip()
        if len(excerpt) > EXCERPT_MAX:
            return jsonify({'message': f'Excerpt must be {EXCERPT_MAX} characters or fewer'}), 400
        article.excerpt = excerpt or None
    if 'body_text' in body:
        text = (body.get('body_text') or '').strip()
        if len(text) > BODY_MAX:
            return jsonify({'message': f'Body must be {BODY_MAX} characters or fewer'}), 400
        article.body_text = text or None
    if 'categories' in body:
        article.categories = normalize_categories(body.get('categories')) or ['other']
    if 'image' in body:
        article.image = body.get('image') or None

    db.session.commit()
    return jsonify(make_article_schema(None).dump(article))


@news_article_api.route('/articles/guest/<token>', methods=['DELETE'])
def delete_guest_article(token):
    article = NewsArticle.query.filter_by(guest_manage_token=token).first()
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    db.session.delete(article)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@news_article_api.route('/articles/<int:article_id>', methods=['PATCH'])
@token_required
def edit_article(current_user, article_id):
    article = db.session.get(NewsArticle, article_id)
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    if not _can_manage(article, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    if 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return jsonify({'message': 'Title is required'}), 400
        if len(title) > TITLE_MAX:
            return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400
        article.title = title
    # Only enforced as non-empty for a self-authored post (never imported) --
    # a scraped article legitimately has no body_text (see NewsArticle's
    # docstring) and this same PATCH route is also how an admin edits those.
    if 'excerpt' in body:
        excerpt = (body.get('excerpt') or '').strip()
        if not article.imported and not excerpt:
            return jsonify({'message': 'A short snippet/headline (excerpt) is required'}), 400
        if len(excerpt) > EXCERPT_MAX:
            return jsonify({'message': f'Excerpt must be {EXCERPT_MAX} characters or fewer'}), 400
        article.excerpt = excerpt or None
    if 'body_text' in body:
        text = (body.get('body_text') or '').strip()
        if not article.imported and not text:
            return jsonify({'message': 'The full article text (body_text) is required'}), 400
        if len(text) > BODY_MAX:
            return jsonify({'message': f'Body must be {BODY_MAX} characters or fewer'}), 400
        article.body_text = text or None
    if 'categories' in body:
        categories = normalize_categories(body.get('categories'))
        if not categories:
            return jsonify({'message': 'At least one category is required'}), 400
        article.categories = categories
    if 'image' in body:
        article.image = body.get('image') or None

    db.session.commit()
    return jsonify(make_article_schema(current_user).dump(article))


@news_article_api.route('/articles/<int:article_id>', methods=['DELETE'])
@token_required
def delete_article(current_user, article_id):
    article = db.session.get(NewsArticle, article_id)
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    if not _can_manage(article, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(article)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@news_article_api.route('/articles/<int:article_id>/like', methods=['POST'])
@token_required
def like_article(current_user, article_id):
    article = db.session.get(NewsArticle, article_id)
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    existing = NewsArticleLike.query.filter_by(article_id=article_id, user_id=current_user.public_id).first()
    if not existing:
        db.session.add(NewsArticleLike(article_id=article_id, user_id=current_user.public_id))
        db.session.commit()
    return jsonify({'liked': True})


@news_article_api.route('/articles/<int:article_id>/like', methods=['DELETE'])
@token_required
def unlike_article(current_user, article_id):
    like = NewsArticleLike.query.filter_by(article_id=article_id, user_id=current_user.public_id).first()
    if like:
        db.session.delete(like)
        db.session.commit()
    return jsonify({'liked': False})


@news_article_api.route('/my/articles', methods=['GET'])
@token_required
def my_articles(current_user):
    rows = (NewsArticle.query.options(*_feed_options())
            .filter_by(created_by=current_user.public_id, imported=False)
            .order_by(NewsArticle.pub_date.desc()).all())
    return jsonify({'articles': make_article_schema(current_user, many=True).dump(rows)})


@news_article_api.route('/upload', methods=['POST'])
@token_required
def news_upload(_current_user):
    filename = upload_file(request)
    if not filename:
        return jsonify({'message': 'Upload failed'}), 400
    return jsonify(filename)


# ── Moderation (scraped-article approval queue) ────────────────────────────

@news_article_api.route('/admin/pending', methods=['GET'])
@admin_required
def list_pending(current_user):
    """Scraped articles (imported=True) AND guest submissions (imported=
    False, created_by=None) both land here now -- this used to require
    imported=True, which would have hidden every guest submission from
    this queue entirely (approved_to_publish=None is the one thing both
    share; a logged-in user's own post never has it, since create_article
    always sets True immediately)."""
    rows = (NewsArticle.query.options(*_feed_options())
            .filter_by(approved_to_publish=None)
            .order_by(NewsArticle.pub_date.desc()).all())
    return jsonify({'articles': make_article_schema(current_user, many=True).dump(rows)})


@news_article_api.route('/admin/articles/<int:article_id>/approve', methods=['POST'])
@admin_required
def approve_article(current_user, article_id):
    article = db.session.get(NewsArticle, article_id)
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    article.approved_to_publish = True
    db.session.commit()
    return jsonify(make_article_schema(current_user).dump(article))


@news_article_api.route('/admin/articles/<int:article_id>/reject', methods=['POST'])
@admin_required
def reject_article(current_user, article_id):
    article = db.session.get(NewsArticle, article_id)
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    article.approved_to_publish = False
    db.session.commit()
    return jsonify(make_article_schema(current_user).dump(article))
