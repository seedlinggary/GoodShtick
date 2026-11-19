"""Standalone correctness check for the giveaway system's core invariants.

There is no pytest/test-DB convention anywhere else in this codebase
(checked: no test_*.py files, no pytest in requirements.txt), and the only
database available is the real Supabase instance the dev server itself
talks to -- so rather than invent a whole parallel test-DB setup for one
feature, this creates its own clearly-tagged, disposable rows (every slug/
email contains SELFTEST_TAG) and deletes every one of them in a `finally`
block regardless of outcome.

Run directly from the backend project root (same FLASK_APP/.env as the
dev server):

    python -m backend.giveaways.selftest

Business-logic route functions are called directly -- the admin-only ones
via their `__wrapped__` attribute, which `functools.wraps` (used by
`role_required` in security.py) preserves, pointing at the function BEFORE
`@super_admin_required` wraps it -- inside a bare `test_request_context`,
instead of going through real HTTP plus a minted JWT. This exercises the
exact same code every real request runs (JSON body parsing, DB writes,
constraint checks) without logging in as anyone, real or fake; the one
throwaway User row created below exists purely to satisfy the `created_by`/
`drawn_by` foreign keys, never to authenticate as.

Covers three of the plan's four explicitly-called-out invariants:

  1. Duplicate-email / duplicate-participation rejection -- the same email
     entering the same campaign twice must never create a second
     GiveawayParticipation row.
  2. Referral crediting -- only on the REFERRED friend's verification (not
     on raw entry), exactly once even if verification is somehow repeated
     (also proves "no duplicate referral rewards").
  3. Draw-snapshot immutability -- drawing again against an already-drawn
     snapshot must add a backup row, never change the original winner.

A dedicated "self-referral" test is deliberately NOT included: tracing the
actual code path shows it's structurally unreachable, not untested. Self-
referral requires the referring participant_id to already have a
participation row in this same campaign under this same referral_code --
but `enter_giveaway`'s existing-participation check (same campaign_id +
participant_id) runs BEFORE the referral-code lookup and always short-
circuits first in that exact situation, so the dedicated guard in the
referral-lookup branch can never actually fire via the public API. It's
kept as harmless defense-in-depth (see that comment in routes/giveaway.py)
in case the dedup check's ordering ever changes, but there is no separate
scenario to exercise it against today.
"""
import sys
import uuid
from werkzeug.security import generate_password_hash

from config import application, db
from backend.user.modals.user import User
from backend.user.modals.audit_log import AuditLog
from backend.giveaways.modals.giveaway import (
    GiveawayCampaign, GiveawayEntryAction, GiveawayParticipant, GiveawayParticipation,
    GiveawayEntry, GiveawayDrawSnapshot, GiveawayDraw, GiveawayEntryThrottle,
)
from backend.giveaways.routes import giveaway as routes
from backend.campaigns.modals.campaign import MarketingCampaign

SELFTEST_TAG = 'selftest-giveaways'
# enter_giveaway rejects a request with no/bot-like User-Agent (see
# _looks_like_bot_ua in routes/giveaway.py) -- test_request_context sends
# no headers by default, so every call into that endpoint needs this to
# look like a real browser hitting the public form.
BROWSER_HEADERS = {'User-Agent': 'Mozilla/5.0 (Selftest Browser)'}


class FakeAdmin:
    def __init__(self, public_id):
        self.public_id = public_id


def _json(result):
    resp = result[0] if isinstance(result, tuple) else result
    return resp.get_json()


def _cleanup():
    campaigns = GiveawayCampaign.query.filter(GiveawayCampaign.slug.like(f'{SELFTEST_TAG}%')).all()
    campaign_ids = [c.id for c in campaigns]
    marketing_ids = [c.marketing_campaign_id for c in campaigns if c.marketing_campaign_id]
    if campaign_ids:
        GiveawayDraw.query.filter(GiveawayDraw.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
        GiveawayDrawSnapshot.query.filter(GiveawayDrawSnapshot.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
        part_ids = [p.id for p in GiveawayParticipation.query.filter(GiveawayParticipation.campaign_id.in_(campaign_ids)).all()]
        if part_ids:
            GiveawayEntry.query.filter(GiveawayEntry.participation_id.in_(part_ids)).delete(synchronize_session=False)
            GiveawayParticipation.query.filter(GiveawayParticipation.id.in_(part_ids)).delete(synchronize_session=False)
        GiveawayEntryAction.query.filter(GiveawayEntryAction.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
        GiveawayCampaign.query.filter(GiveawayCampaign.id.in_(campaign_ids)).delete(synchronize_session=False)
    if marketing_ids:
        MarketingCampaign.query.filter(MarketingCampaign.id.in_(marketing_ids)).delete(synchronize_session=False)
    GiveawayParticipant.query.filter(GiveawayParticipant.email.like(f'%{SELFTEST_TAG}%')).delete(synchronize_session=False)

    # test_request_context never sets X-Forwarded-For, so real_client_ip()
    # falls back to the 'unknown' sentinel for every call this script
    # makes -- a real request never produces that identity (Vercel always
    # sets X-Forwarded-For), so this bucket is purely a test-harness
    # artifact. Reset it each run, or repeated runs on the same day would
    # eventually trip GIVEAWAY_ENTRY_DAILY_CAP against themselves.
    GiveawayEntryThrottle.query.filter_by(identity='ip:unknown').delete(synchronize_session=False)

    test_user_ids = [u.public_id for u in User.query.filter(User.email.like(f'%{SELFTEST_TAG}%')).all()]
    if test_user_ids:
        # log_admin_action (called by update_campaign/freeze_draw/run_draw
        # during the test run) wrote AuditLog rows referencing this
        # throwaway admin -- its own FK has no cascade, so those have to
        # go before the user row can be deleted.
        AuditLog.query.filter(AuditLog.actor_public_id.in_(test_user_ids)).delete(synchronize_session=False)
        User.query.filter(User.public_id.in_(test_user_ids)).delete(synchronize_session=False)
    db.session.commit()


def run():
    failures = []

    def check(label, condition):
        status = 'PASS' if condition else 'FAIL'
        print(f'  [{status}] {label}')
        if not condition:
            failures.append(label)

    with application.app_context():
        _cleanup()  # in case a prior run crashed before its own cleanup

        admin_user = User(
            public_id=str(uuid.uuid4()), first_name='Self', last_name='Test',
            password=generate_password_hash('not-a-real-login', method='pbkdf2:sha256'),
            email=f'admin+{SELFTEST_TAG}@example.com', profile_name=f'{SELFTEST_TAG}-admin',
        )
        db.session.add(admin_user)
        db.session.commit()
        fake_admin = FakeAdmin(admin_user.public_id)

        try:
            slug = f'{SELFTEST_TAG}-{uuid.uuid4().hex[:8]}'

            with application.test_request_context('/giveaways', method='POST', json={'name': 'Selftest Campaign', 'slug': slug}):
                campaign_data = _json(routes.create_campaign.__wrapped__(fake_admin))
            campaign_id = campaign_data['id']

            default_action = GiveawayEntryAction.query.filter_by(campaign_id=campaign_id, action_key='email_signup').first()
            check('a new campaign is created with one enabled default entry action (no admin setup needed)',
                  default_action is not None and default_action.is_enabled)

            with application.test_request_context(f'/giveaways/{campaign_id}', method='PATCH', json={'status': 'active'}):
                activate_result = _json(routes.update_campaign.__wrapped__(fake_admin, campaign_id))
            check('a brand-new campaign can go active immediately, with no entry actions added by hand',
                  activate_result.get('status') == 'active')

            with application.test_request_context(f'/giveaways/{campaign_id}/entry-actions', method='POST', json={
                'action_key': 'referral_qualified', 'label': 'Referred a friend', 'entry_quantity': 5, 'verification_method': 'auto',
            }):
                routes.create_entry_action.__wrapped__(fake_admin, campaign_id)

            with application.test_request_context(f'/giveaways/{campaign_id}', method='PATCH', json={'status': 'active'}):
                routes.update_campaign.__wrapped__(fake_admin, campaign_id)

            # ── Test 1: duplicate-email / duplicate-participation ──
            email_a = f'a+{SELFTEST_TAG}@example.com'
            with application.test_request_context(f'/giveaways/public/{slug}/enter', method='POST', json={'name': 'A', 'email': email_a}, headers=BROWSER_HEADERS):
                enter_1 = _json(routes.enter_giveaway(slug))
            with application.test_request_context(f'/giveaways/public/{slug}/enter', method='POST', json={'name': 'A', 'email': email_a}, headers=BROWSER_HEADERS):
                enter_2 = _json(routes.enter_giveaway(slug))

            participant_a = GiveawayParticipant.query.filter_by(email=email_a).first()
            participations_a = GiveawayParticipation.query.filter_by(campaign_id=campaign_id, participant_id=participant_a.id).all()
            check('duplicate /enter with the same email creates only one participation', len(participations_a) == 1)
            check('the duplicate /enter call reports the SAME referral_code back', enter_1['referral_code'] == enter_2['referral_code'])
            check('GiveawayParticipant.email is globally unique per person', GiveawayParticipant.query.filter_by(email=email_a).count() == 1)

            participation_a = participations_a[0]
            with application.test_request_context(f'/giveaways/public/verify/{participation_a.verify_token}'):
                routes.verify_participation(participation_a.verify_token)
            db.session.refresh(participation_a)

            # ── Test 2: referral crediting only on verify, never duplicated ──
            email_b = f'b+{SELFTEST_TAG}@example.com'
            with application.test_request_context(f'/giveaways/public/{slug}/enter', method='POST',
                                                    json={'name': 'B', 'email': email_b, 'ref': participation_a.referral_code},
                                                    headers=BROWSER_HEADERS):
                routes.enter_giveaway(slug)
            participant_b = GiveawayParticipant.query.filter_by(email=email_b).first()
            participation_b = GiveawayParticipation.query.filter_by(campaign_id=campaign_id, participant_id=participant_b.id).first()

            check('B\'s participation records A as the referrer', participation_b.referrer_participation_id == participation_a.id)
            pre_verify_credit = GiveawayEntry.query.filter_by(
                participation_id=participation_a.id, action_key='referral_qualified').count()
            check('A is NOT credited before B verifies', pre_verify_credit == 0)

            with application.test_request_context(f'/giveaways/public/verify/{participation_b.verify_token}'):
                routes.verify_participation(participation_b.verify_token)
            with application.test_request_context(f'/giveaways/public/verify/{participation_b.verify_token}'):
                routes.verify_participation(participation_b.verify_token)  # repeat -- must be idempotent

            credit_rows = GiveawayEntry.query.filter_by(participation_id=participation_a.id, action_key='referral_qualified').all()
            check('A is credited exactly once for referring B, even after a repeated verify call', len(credit_rows) == 1)
            check('the referral-credit entry is tied to B specifically (related_participation_id)',
                  bool(credit_rows) and credit_rows[0].related_participation_id == participation_b.id)

            # ── Test: /my -- a logged-in site member's referral dashboard,
            # matched purely by email (not by a user_id backfilled at entry
            # time, which a guest entry would never have gotten). ──
            member_user = User(
                public_id=str(uuid.uuid4()), first_name='A', last_name='Member',
                password=generate_password_hash('not-a-real-login', method='pbkdf2:sha256'),
                email=email_a, profile_name=f'{SELFTEST_TAG}-member',
            )
            db.session.add(member_user)
            db.session.commit()

            with application.test_request_context('/giveaways/my'):
                my_data = _json(routes.my_giveaways.__wrapped__(member_user))
            my_campaign = next((p for p in my_data['participations'] if p['campaign_slug'] == slug), None)
            check('/my finds a participation for a user whose login email matches the giveaway entry email',
                  my_campaign is not None)
            check('/my reports the live entry total, matching _entry_total directly',
                  bool(my_campaign) and my_campaign['entry_total'] == routes._entry_total(participation_a.id))
            check('/my lists B by name as a referred signup under A',
                  bool(my_campaign) and any(r['name'] == 'B' for r in my_campaign['referred_signups']))
            check('/my never exposes the referred friend\'s email address',
                  bool(my_campaign) and not any('email' in r for r in my_campaign['referred_signups']))

            # ── Test 3: draw-snapshot immutability ──
            with application.test_request_context(f'/giveaways/{campaign_id}/draw/freeze', method='POST', json={}):
                snapshot_data = _json(routes.freeze_draw.__wrapped__(fake_admin, campaign_id))
            check('both verified participants are in the frozen eligible pool', snapshot_data['eligible_count'] == 2)

            with application.test_request_context(f'/giveaways/{campaign_id}/draw', method='POST', json={}):
                draw_1 = _json(routes.run_draw.__wrapped__(fake_admin, campaign_id))
            first_winner_draw = GiveawayDraw.query.filter_by(campaign_id=campaign_id, is_backup=False).first()
            check('the first draw call picks exactly one non-backup winner', len(draw_1['drawn']) == 1 and not draw_1['drawn'][0]['is_backup'])

            with application.test_request_context(f'/giveaways/{campaign_id}/draw', method='POST', json={}):
                draw_2 = _json(routes.run_draw.__wrapped__(fake_admin, campaign_id))
            db.session.refresh(first_winner_draw)

            check('drawing again against the same snapshot adds a BACKUP, not a second winner',
                  len(draw_2['drawn']) == 1 and draw_2['drawn'][0]['is_backup'])
            check('the original winner draw row is unchanged by the second draw call',
                  first_winner_draw.winner_participation_id == draw_1['drawn'][0]['participation_id'])
            check('the backup is a DIFFERENT participation than the original winner',
                  draw_2['drawn'][0]['participation_id'] != draw_1['drawn'][0]['participation_id'])
            check('exactly 2 draw rows exist for this campaign after both calls',
                  GiveawayDraw.query.filter_by(campaign_id=campaign_id).count() == 2)

            # ── Test 4: manual-review entries don't count until approved,
            # and a required action gates draw eligibility -- own isolated
            # campaign so this doesn't disturb the draw-immutability pool
            # above. ──
            slug2 = f'{SELFTEST_TAG}-{uuid.uuid4().hex[:8]}'
            with application.test_request_context('/giveaways', method='POST', json={'name': 'Selftest Campaign 2', 'slug': slug2}):
                campaign2_data = _json(routes.create_campaign.__wrapped__(fake_admin))
            campaign2_id = campaign2_data['id']
            # (campaign2 already has its default 'email_signup' action from create_campaign)
            with application.test_request_context(f'/giveaways/{campaign2_id}/entry-actions', method='POST', json={
                'action_key': 'upload_proof', 'label': 'Upload proof', 'entry_quantity': 10,
                'verification_method': 'manual', 'is_required': True,
            }):
                routes.create_entry_action.__wrapped__(fake_admin, campaign2_id)
            with application.test_request_context(f'/giveaways/{campaign2_id}', method='PATCH', json={'status': 'active'}):
                routes.update_campaign.__wrapped__(fake_admin, campaign2_id)

            email_c = f'c+{SELFTEST_TAG}@example.com'
            with application.test_request_context(f'/giveaways/public/{slug2}/enter', method='POST',
                                                    json={'name': 'C', 'email': email_c}, headers=BROWSER_HEADERS):
                enter_c = _json(routes.enter_giveaway(slug2))
            participant_c = GiveawayParticipant.query.filter_by(email=email_c).first()
            participation_c = GiveawayParticipation.query.filter_by(campaign_id=campaign2_id, participant_id=participant_c.id).first()
            with application.test_request_context(f'/giveaways/public/verify/{participation_c.verify_token}'):
                routes.verify_participation(participation_c.verify_token)

            with application.test_request_context(f'/giveaways/public/{slug2}/action', method='POST',
                                                    json={'token': enter_c['participation_token'], 'action_key': 'upload_proof', 'evidence': 'see attached'}):
                submit_result = _json(routes.complete_action(slug2))
            check('submitting a manual action reports pending_review=True', submit_result['pending_review'] is True)
            check('a pending-review entry does NOT count toward entry_total yet', routes._entry_total(participation_c.id) == 1)

            with application.test_request_context(f'/giveaways/{campaign2_id}/draw/freeze', method='POST', json={}):
                snapshot_before = _json(routes.freeze_draw.__wrapped__(fake_admin, campaign2_id))
            check('a verified participant missing an un-approved REQUIRED action is excluded from the eligible pool',
                  snapshot_before['eligible_count'] == 0)

            pending_entry = GiveawayEntry.query.filter_by(participation_id=participation_c.id, action_key='upload_proof').first()
            with application.test_request_context(f'/giveaways/entries/{pending_entry.id}/approve', method='POST', json={}):
                routes.approve_entry.__wrapped__(fake_admin, pending_entry.id)
            check('approving the manual entry makes it count', routes._entry_total(participation_c.id) == 11)

            with application.test_request_context(f'/giveaways/{campaign2_id}/draw/freeze', method='POST', json={}):
                snapshot_after = _json(routes.freeze_draw.__wrapped__(fake_admin, campaign2_id))
            check('after approval, that same participant IS in a newly-frozen eligible pool', snapshot_after['eligible_count'] == 1)

        finally:
            _cleanup()

    print()
    if failures:
        print(f'{len(failures)} check(s) FAILED:')
        for f in failures:
            print(f'  - {f}')
        sys.exit(1)
    print('All checks passed.')


if __name__ == '__main__':
    run()
