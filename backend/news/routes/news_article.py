from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, super_admin_required
from upload import upload_file
from backend.news.modals.news import NewsArticle, NewsArticleLike, CATEGORIES, slugify
from backend.news.schemas.news import NewsArticleCardSchema, make_article_schema

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
    """Scraped articles only show once approved; user posts always show
    (they publish immediately -- see NewsArticle's own docstring)."""
    return query.filter(db.or_(NewsArticle.imported.is_(False), NewsArticle.approved_to_publish.is_(True)))


@news_article_api.route('/categories', methods=['GET'])
def list_categories():
    return jsonify({'categories': list(CATEGORIES)})


@news_article_api.route('/stats', methods=['GET'])
def news_stats():
    base = _public_filter(NewsArticle.query)
    total = base.count()
    by_category = dict(
        db.session.query(NewsArticle.category, func.count(NewsArticle.id))
        .filter(db.or_(NewsArticle.imported.is_(False), NewsArticle.approved_to_publish.is_(True)))
        .group_by(NewsArticle.category).all()
    )
    contributors = (db.session.query(func.count(func.distinct(NewsArticle.created_by)))
                    .filter(NewsArticle.created_by.isnot(None), NewsArticle.imported.is_(False)).scalar() or 0)
    return jsonify({'articles': total, 'contributors': contributors, 'by_category': by_category})


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
        if category not in CATEGORIES:
            return jsonify({'message': f'category must be one of: {", ".join(CATEGORIES)}'}), 400
        query = query.filter(NewsArticle.category == category)
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
    exclusively by news_scraper.py, never through this endpoint."""
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
    category = (body.get('category') or 'other').strip().lower()
    if category not in CATEGORIES:
        return jsonify({'message': f'category must be one of: {", ".join(CATEGORIES)}'}), 400
    source_url = (body.get('source_url') or '').strip()

    article = NewsArticle(
        slug=_unique_slug(title), title=title, created_by=current_user.public_id,
        excerpt=excerpt or None, body_text=body_text or None, category=category,
        image=body.get('image') or None, source_url=source_url or None,
        imported=False, approved_to_publish=True,
    )
    db.session.add(article)
    db.session.commit()
    return jsonify(make_article_schema(current_user).dump(article)), 201


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
    if 'category' in body:
        category = (body.get('category') or 'other').strip().lower()
        if category not in CATEGORIES:
            return jsonify({'message': f'category must be one of: {", ".join(CATEGORIES)}'}), 400
        article.category = category
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
@super_admin_required
def list_pending(current_user):
    rows = (NewsArticle.query.options(*_feed_options())
            .filter_by(imported=True, approved_to_publish=None)
            .order_by(NewsArticle.pub_date.desc()).all())
    return jsonify({'articles': make_article_schema(current_user, many=True).dump(rows)})


@news_article_api.route('/admin/articles/<int:article_id>/approve', methods=['POST'])
@super_admin_required
def approve_article(current_user, article_id):
    article = db.session.get(NewsArticle, article_id)
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    article.approved_to_publish = True
    db.session.commit()
    return jsonify(make_article_schema(current_user).dump(article))


@news_article_api.route('/admin/articles/<int:article_id>/reject', methods=['POST'])
@super_admin_required
def reject_article(current_user, article_id):
    article = db.session.get(NewsArticle, article_id)
    if not article:
        return jsonify({'message': 'Article not found'}), 404
    article.approved_to_publish = False
    db.session.commit()
    return jsonify(make_article_schema(current_user).dump(article))
