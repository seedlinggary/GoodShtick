"""Thin REST client for Apify's actor platform -- used by connectors
(nadlan_gov.py, rmi_tenders.py) for the two government sources that have no
API of their own reachable without impersonating a browser (see those
files' docstrings for what was actually tried). Apify is a normal,
documented, API-token-authenticated paid service: calling it is an
ordinary API client relationship, not scraping -- Apify's own actors
handle whatever access their target site needs (e.g. an Israeli
residential proxy for nadlan.gov.il) as part of their own product, under
their own terms, not ours."""
import os

import requests

APIFY_BASE_URL = 'https://api.apify.com/v2'
# The run-sync endpoint waits for the actor to finish before responding --
# give it real headroom beyond Apify's own ceiling rather than timing out
# client-side on a slow run.
DEFAULT_TIMEOUT = 300


class ApifyNotConfigured(Exception):
    pass


def _token():
    token = os.environ.get('APIFY_API_TOKEN')
    if not token:
        raise ApifyNotConfigured(
            'APIFY_API_TOKEN is not set. Sign up at apify.com, add payment, and set this env var '
            'before running anything that depends on apify_client -- every actor run here is billed.'
        )
    return token


def run_actor_sync(actor_id, run_input, timeout=DEFAULT_TIMEOUT):
    """Runs an Apify actor and waits for it to finish, returning its
    dataset items directly as a list of dicts in one HTTP call (no manual
    polling of run status). `actor_id` is the actor's store id in
    "owner~name" form (e.g. "swerve~nadlan-gov-deals")."""
    url = f'{APIFY_BASE_URL}/acts/{actor_id}/run-sync-get-dataset-items'
    resp = requests.post(url, params={'token': _token()}, json=run_input, timeout=timeout + 30)
    resp.raise_for_status()
    return resp.json()
