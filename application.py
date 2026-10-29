from flask import jsonify, request, make_response
from datetime import datetime, timedelta, timezone
from werkzeug.security import check_password_hash
import jwt
from config import application, db

# Route blueprints
from backend.user.routes.user import user_api
from backend.user.routes.admin import admin_api
from backend.user.routes.game import game_api
from backend.shtick.routes.generalc import generalc_api
from backend.shtick.routes.shtick import shtick_api
from backend.shtick.routes.like import like_api
from backend.shtick.routes.comment import comment_api
from backend.ads.routes.ads import ads_api
from backend.notifications.routes.notification import notification_api
from backend.media.routes.media import media_api
from backend.hock.routes.hock_post import hock_post_api
from backend.hock.routes.hock_comment import hock_comment_api
from backend.content_pipeline.routes.ai_content import ai_content_api
from backend.content_pipeline.routes.scraper import scraper_api
from backend.content_pipeline.routes.youtube import youtube_api
from backend.contact.routes.contact import contact_api
from backend.tachlis.routes.tachlis_post import tachlis_api
from backend.analytics.routes.visitor import analytics_api
from backend.user.routes.sso import sso_api
from backend.business.routes.business import business_api
from backend.business.routes.business_post import business_post_api
from backend.business.routes.business_rating import business_rating_api
from backend.business.routes.business_comment import business_comment_api
from backend.business.routes.social import social_api
from backend.business.routes.business_analytics import business_analytics_api
from backend.business.routes.business_redemption import redemption_api
from backend.business.routes.business_follow import follow_api
from backend.business.routes.business_lead import lead_api
from backend.business.routes.business_question import question_api
from backend.business.routes.business_referral import referral_api
from backend.business.routes.business_owner_tools import owner_tools_api
from backend.business.routes.business_feedback import feedback_api
from backend.business.routes.loyalty_card import loyalty_api
from backend.business.routes.business_referral_code import referral_code_api
from backend.business.routes.business_insights import insights_api
from backend.business.routes.community import community_api
from backend.business.routes.minyan import minyan_api
from backend.business.routes.admin_integrations import admin_integrations_api
from backend.estates.routes.estates import estates_api
from backend.estates.routes.estates_group_buy import group_buy_api
from backend.finance.routes.finance_market import finance_market_api
from backend.finance.routes.finance_budget import finance_budget_api
from backend.finance.routes.form106 import finance_form106_api
from backend.torah.routes.torah_post import torah_post_api
from backend.torah.routes.torah_sefaria import torah_sefaria_api
from backend.torah.routes.torah_zmanim import torah_zmanim_api
from backend.torah.routes.torah_sheets import torah_sheets_api
from backend.feed.routes.aggregate import feed_api
from backend.banner.routes.banner import banner_api
from backend.search.routes.search import search_api
from backend.alerts.routes.alert import alerts_api, link_alerts_to_user
from backend.news.routes.news_article import news_article_api
from backend.news.routes.news_scraper import news_scraper_api

# Models — imported so SQLAlchemy's mapper registry can resolve string-based
# relationship() references, and so Flask-Migrate autogenerate sees them.
from backend.user.modals.user import User
from backend.user.modals.game_score import GameScore
from backend.user.modals.audit_log import AuditLog
from backend.shtick.modals.shtick import Shtick
from backend.shtick.modals.generalc import Generalc
from backend.shtick.modals.like import Like
from backend.shtick.modals.comment import Comment
from backend.shtick.modals.content import Content
from backend.shtick.modals.url import Url
from backend.shtick.modals.picture import Picture
from backend.ads.modals.ad import Ad
from backend.ads.modals.ad_impression import AdImpression
from backend.ads.modals.ad_click import AdClick
from backend.notifications.modals.notification import Notification
from backend.hock.modals.hock_post import HockPost
from backend.hock.modals.hock_comment import HockComment
from backend.hock.modals.hock_like import HockPostLike, HockCommentLike
from backend.content_pipeline.modals.scraped_article import ScrapedArticle
from backend.content_pipeline.modals.youtube_channel import YoutubeChannel, YoutubeVideoPost
from backend.tachlis.modals.tachlis_post import TachlisPost
from backend.analytics.modals.visitor import VisitorSession, VisitorEvent
from backend.business.modals.business import Business, BusinessLocation
from backend.business.modals.business_claim import BusinessClaim
from backend.business.modals.business_post import BusinessPost
from backend.business.modals.business_rating import BusinessRating
from backend.business.modals.business_comment import BusinessComment
from backend.business.modals.social_account import SocialAccount
from backend.business.modals.social_post import SocialPost, SocialPostTarget
from backend.business.modals.business_redemption import BusinessRedemption
from backend.business.modals.business_follow import BusinessFollow
from backend.business.modals.business_lead import BusinessLead
from backend.business.modals.business_question import BusinessQuestion
from backend.business.modals.business_referral import BusinessReferralPost, BusinessReferralReply
from backend.business.modals.business_feedback import BusinessFeedback
from backend.business.modals.loyalty_card import LoyaltyCard
from backend.business.modals.business_referral_code import BusinessReferral, BusinessReferralUse
from backend.business.modals.platform_credential import PlatformCredential
from backend.estates.modals.estates import (
    EstatesListing, EstatesListingPhoto, EstatesListingLike,
    EstatesGroupBuy, EstatesGroupBuyPhoto, EstatesGroupBuyMember,
)
from backend.finance.modals.finance import (
    FinanceDataCache, FinanceWatchlistItem, FinanceBudget, FinanceBudgetCategory, FinanceSavedScenario,
)
from backend.torah.modals.torah import (
    TorahPost, TorahPostPhoto, TorahPostLike, SefariaCache,
    TorahSourceSheet, TorahSourceSheetItem,
)
from backend.news.modals.news import NewsArticle, NewsArticleLike

application.register_blueprint(user_api)
application.register_blueprint(admin_api)
application.register_blueprint(game_api)
application.register_blueprint(generalc_api)
application.register_blueprint(shtick_api)
application.register_blueprint(like_api)
application.register_blueprint(comment_api)
application.register_blueprint(ads_api)
application.register_blueprint(notification_api)
application.register_blueprint(media_api)
application.register_blueprint(hock_post_api)
application.register_blueprint(hock_comment_api)
application.register_blueprint(ai_content_api)
application.register_blueprint(scraper_api)
application.register_blueprint(youtube_api)
application.register_blueprint(contact_api)
application.register_blueprint(tachlis_api)
application.register_blueprint(analytics_api)
application.register_blueprint(sso_api)
application.register_blueprint(business_api)
application.register_blueprint(business_post_api)
application.register_blueprint(business_rating_api)
application.register_blueprint(business_comment_api)
application.register_blueprint(social_api)
application.register_blueprint(business_analytics_api)
application.register_blueprint(redemption_api)
application.register_blueprint(follow_api)
application.register_blueprint(lead_api)
application.register_blueprint(question_api)
application.register_blueprint(referral_api)
application.register_blueprint(owner_tools_api)
application.register_blueprint(feedback_api)
application.register_blueprint(loyalty_api)
application.register_blueprint(referral_code_api)
application.register_blueprint(insights_api)
application.register_blueprint(admin_integrations_api)
application.register_blueprint(community_api)
application.register_blueprint(minyan_api)
application.register_blueprint(estates_api)
application.register_blueprint(group_buy_api)
application.register_blueprint(finance_market_api)
application.register_blueprint(finance_budget_api)
application.register_blueprint(finance_form106_api)
application.register_blueprint(torah_post_api)
application.register_blueprint(torah_sefaria_api)
application.register_blueprint(torah_zmanim_api)
application.register_blueprint(torah_sheets_api)
application.register_blueprint(news_article_api)
application.register_blueprint(news_scraper_api)
application.register_blueprint(feed_api)
application.register_blueprint(alerts_api)
application.register_blueprint(banner_api)
application.register_blueprint(search_api)

# Schema is managed exclusively by Alembic migrations (flask db upgrade).
# db.create_all() must NOT run here: on serverless it fires on every cold
# start, adding a schema round-trip to Postgres before any request is served,
# and it can race ahead of a pending migration (this happened once already).


@application.route('/login', methods=['GET'])
def login():
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        return make_response('Could not verify', 401, {'WWW-Authenticate': 'Basic realm="Login required"'})

    user = User.query.filter_by(email=auth.username).first()
    if not user:
        return make_response('Could not verify', 401, {'WWW-Authenticate': 'Basic realm="Login required"'})

    if not check_password_hash(user.password, auth.password):
        return make_response('Could not verify', 401, {'WWW-Authenticate': 'Basic realm="Login required"'})

    # First person ever to log in becomes super_admin
    if not User.query.filter(User.role.in_(['admin', 'super_admin'])).first():
        user.role = 'super_admin'

    user.last_login = datetime.now(timezone.utc)
    db.session.commit()
    link_alerts_to_user(user)

    token = jwt.encode(
        {'public_id': user.public_id, 'exp': datetime.now(timezone.utc) + timedelta(days=7)},
        application.config['SECRET_KEY'],
        algorithm='HS256'
    )
    return jsonify({'token': token, 'role': user.role, 'is_boss': user.is_boss,
                    'profile_name': user.profile_name, 'public_id': user.public_id})


@application.errorhandler(404)
def not_found(_):
    return jsonify({'message': 'Resource not found'}), 404


@application.errorhandler(500)
def server_error(_):
    return jsonify({'message': 'Internal server error'}), 500


# ── Seed command: flask seed-posts ───────────────────────────────────────────
@application.cli.command('seed-posts')
def seed_posts():
    """Insert 10 sample posts (pending approval) plus default categories."""
    _seed_categories()
    user = User.query.first()
    if not user:
        print('No users found — register an account first, then run flask seed-posts.')
        return
    _seed_shticks(user)
    print('Seed complete.')


def _seed_categories():
    defaults = ['Funny', 'Inspiring', 'Videos', 'Tech', 'News', 'Sports', 'Music', 'Random', 'Quotes', 'Viral']
    added = 0
    for name in defaults:
        if not Generalc.query.filter_by(name=name).first():
            db.session.add(Generalc(name=name))
            added += 1
    db.session.commit()
    if added:
        print(f'Created {added} categories.')


def _seed_shticks(user):
    cats = {c.name: c for c in Generalc.query.all()}

    posts = [
        {
            'caption': 'The secret of getting ahead is getting started',
            'credit': 'Mark Twain',
            'generalc': 'Quotes',
            'content': 'The secret of getting ahead is getting started. The secret of getting started is breaking your complex, overwhelming tasks into small, manageable tasks, and then starting on the first one.',
        },
        {
            'caption': 'Carl Sagan on the Pale Blue Dot — this will give you chills',
            'credit': 'Carl Sagan',
            'generalc': 'Inspiring',
            'url': 'https://www.youtube.com/watch?v=GO5FwsblpT8',
        },
        {
            'caption': 'SNL — Every State\'s Slogan',
            'credit': 'Saturday Night Live',
            'generalc': 'Funny',
            'url': 'https://www.youtube.com/watch?v=F57P9C4SAW4',
        },
        {
            'caption': 'Elon on why he thinks we\'re likely living in a simulation',
            'credit': 'Elon Musk',
            'generalc': 'Tech',
            'url': 'https://twitter.com/elonmusk/status/1590044369476767744',
        },
        {
            'caption': 'Why procrastination is about emotions, not time management',
            'credit': 'TED-Ed',
            'generalc': 'Inspiring',
            'url': 'https://www.youtube.com/watch?v=mhFQA998WiA',
        },
        {
            'caption': 'Two things are infinite: the universe and human stupidity',
            'credit': 'Albert Einstein',
            'generalc': 'Funny',
            'content': 'Two things are infinite: the universe and human stupidity; and I\'m not sure about the universe.',
        },
        {
            'caption': 'OpenAI releases o3 model — and the AI race just went nuclear',
            'credit': 'The Verge',
            'generalc': 'Tech',
            'url': 'https://www.theverge.com/2024/12/20/24326141/openai-o3-reasoning-model-safety-benchmark',
        },
        {
            'caption': 'Tiny Desk Concert: Chappell Roan',
            'credit': 'NPR Music',
            'generalc': 'Music',
            'url': 'https://www.youtube.com/watch?v=KrZSaL7w-gY',
        },
        {
            'caption': 'Life is what happens when you\'re busy making other plans',
            'credit': 'John Lennon',
            'generalc': 'Quotes',
            'content': 'Life is what happens when you\'re busy making other plans. Beautiful Boy (Darling Boy), 1980.',
        },
        {
            'caption': 'A $20 trick that tricks your brain into focusing instantly',
            'credit': 'Andrew Huberman',
            'generalc': 'Viral',
            'url': 'https://www.youtube.com/watch?v=If58MdFVMRM',
            'content': 'Dr. Huberman explains the visual focus trick: look at a fixed point for 30-60 seconds before starting work. It triggers the brain\'s alertness circuits without caffeine.',
        },
    ]

    for p in posts:
        cat = cats.get(p['generalc'], cats.get('Random'))
        if not cat:
            continue
        s = Shtick(
            caption=p['caption'],
            credit=p.get('credit', ''),
            specific_category='',
            user_id=user.public_id,
            generalc_id=cat.id
        )
        db.session.add(s)
        db.session.flush()

        s.categories.append(cat)

        if p.get('content'):
            db.session.add(Content(stuff=p['content'], shtick_id=s.id))
        if p.get('url'):
            db.session.add(Url(name=p['url'], shtick_id=s.id))

    db.session.commit()
    print(f'Inserted {len(posts)} posts pending approval.')


# Vercel's Python runtime discovers the WSGI callable by looking for `app`
app = application

if __name__ == '__main__':
    # threaded=True matters in practice: a few routes make slow outbound
    # calls (e.g. torah_sefaria.py's /toc, which can take minutes on a cold
    # cache -- see its own comment), and Flask's dev server is single-
    # threaded by default -- without this, ONE such request blocks every
    # other request on the whole site, local to that one request's duration.
    application.run(debug=True, threaded=True)
