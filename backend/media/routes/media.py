import random
import httpx
from flask import Blueprint, jsonify, Response

media_api = Blueprint('media_api', __name__, url_prefix='/media')

# Each entry fetches one random image URL from a free, keyless animal photo API.
# Fetched server-side (not by the browser) specifically because none of these
# CDNs send Access-Control-Allow-Origin — a browser reading pixel data from
# them directly would taint the canvas. Proxying through our own domain, which
# already sends permissive CORS via the app-wide Flask-CORS config, avoids that
# entirely regardless of what the upstream API does.
def _cat_url():
    return httpx.get('https://api.thecatapi.com/v1/images/search', timeout=6).json()[0]['url']


def _dog_url():
    return httpx.get('https://api.thedogapi.com/v1/images/search', timeout=6).json()[0]['url']


def _duck_url():
    url = httpx.get('https://random-d.uk/api/v2/random', timeout=6).json()['url']
    return url.replace('http://', 'https://')


ANIMAL_SOURCES = [_cat_url, _dog_url, _duck_url]


@media_api.route('/random-animal', methods=['GET'])
def random_animal_image():
    sources = ANIMAL_SOURCES[:]
    random.shuffle(sources)
    for get_url in sources:
        try:
            image_url = get_url()
            resp = httpx.get(image_url, timeout=8, follow_redirects=True)
            resp.raise_for_status()
            content_type = resp.headers.get('content-type', 'image/jpeg')
            return Response(resp.content, mimetype=content_type, headers={
                'Cache-Control': 'no-store',
            })
        except Exception:
            continue
    return jsonify({'message': 'Could not fetch an animal image right now — try again'}), 502
