import os
import uuid

from werkzeug.utils import secure_filename
from supabase import create_client

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'xlsx', 'xlsb', 'csv'}

_supabase_client = None
_bucket_name = None


def _get_supabase():
    global _supabase_client
    if _supabase_client is None:
        url = os.environ.get('SUPABASE_URL', '')
        key = os.environ.get('SUPABASE_API', '')
        _supabase_client = create_client(url, key)
    return _supabase_client


def _get_bucket_name():
    """SUPABASE_BUCKET env var if set, else the first bucket on the project (cached)."""
    global _bucket_name
    if _bucket_name is None:
        _bucket_name = os.environ.get('SUPABASE_BUCKET')
        if not _bucket_name:
            buckets = _get_supabase().storage.list_buckets()
            if not buckets:
                raise RuntimeError('No Supabase storage buckets found — create one or set SUPABASE_BUCKET.')
            _bucket_name = buckets[0].name
    return _bucket_name


def _get_bucket():
    return _get_supabase().storage.from_(_get_bucket_name())


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def upload_file(request):
    """Save the uploaded file to Supabase Storage and return its stored filename."""
    if request.method != 'POST':
        return None
    if 'file' not in request.files:
        return None
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return None

    secure_filename(file.filename)  # validates the name; storage itself uses a generated id below
    ext = file.filename.rsplit('.', 1)[1].lower()
    fname = f'{uuid.uuid4()}.{ext}'
    tmp_path = os.path.join('/tmp', fname)
    file.save(tmp_path)
    try:
        _get_bucket().upload(fname, tmp_path)
    finally:
        os.remove(tmp_path)
    return fname


def get_public_url(filename):
    """Direct CDN URL for a previously-uploaded file — no download/re-encode round trip.

    Requires the Supabase bucket to have public read access enabled.
    """
    if not filename:
        return None
    return _get_bucket().get_public_url(filename)
