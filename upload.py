from flask import flash, redirect
from werkzeug.utils import secure_filename
import os
import uuid
import shutil
from config import  application
# from storage3 import create_client
from supabase import create_client, Client
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'xlsx', 'xlsb', 'csv'}

_supabase_client = None

def _get_supabase():
    global _supabase_client
    if _supabase_client is None:
        url = os.environ.get('SUPABASE_URL', '')
        key = os.environ.get('SUPABASE_API', '')
        _supabase_client = create_client(url, key)
    return _supabase_client



def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def download_images(images_list):
    print(images_list)
    my_bucket = _get_supabase().storage.list_buckets()
    if os.path.exists('downloadimages'):
        shutil.rmtree('downloadimages')
    os.makedirs('downloadimages')
    for name in images_list:
        name_of_file = name +'.jpeg'
        print(name)
        # completeName = os.path.join('downloadimages', name_of_file)
        with open(os.path.join('downloadimages',name_of_file), 'wb+') as f:
            # for name in images_list:
            res = my_bucket[0].download(name)
            f.write(res)
            # completeName = os.path.join('downloadimages', name_of_file)

def upload_file(request):
    if request.method == 'POST':
    # check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            print('hi')
            return None
        file = request.files['file']
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == '':
            flash('No selected file')
            return None
        if file and allowed_file(file.filename):

            filename = secure_filename(file.filename)
            # workbook = Workbook(request.files['data_file'])
            # filename = 'investor_accounting.csv'
            # print((file.content_type))
            res = _get_supabase().storage.list_buckets()
            print(res)
            fname =str(uuid.uuid4())
            file.save(os.path.join(application.config['UPLOAD_FOLDER'], filename))
            # open(f'uploadedFiles/{filename}')
            with open(f'uploadedFiles/{filename}', 'rb') as f:
                # res[0].upload(file=f,path='', file_options={"content-type": "jpg"})
                res[0].upload(fname, f'uploadedFiles/{filename}')
                return fname
    return None
            # print(storage_client)
            # print('helooooooooooooooo')
            # buckets = storage_client.list_buckets()
            # print(buckets)
            # print(dir(storage_client))
            # if not buckets:
            #     storage_client.create_bucket('shtick')
            # bucket = buckets[0]
            # print(dir(bucket))
            # return bucket.upload(filename, file)
            # file.save(os.path.join(application.config['UPLOAD_FOLDER'], filename))
            # return filename



        



# url = f"{os.environ.get('SUPABASE_URL')}/storage/goodshtick"
# key = os.environ.get('SUPABASE_API')
# headers = {"apiKey": key, "Authorization": f"Bearer {key}"}
# storage_client = create_client(url, headers, is_async=False)
# def upload_file(self):
#     # if 'file' not in request.files:
#     #     flash('No file part')
#     #     return redirect('/')
#     # file = request.files['file']
#     # if file.filename == '':
#     #     flash('No selected file')
#     #     return redirect('/')
#     filename = 'good-shtick-backend\brian-tromp-B4VXQIJ_oew-unsplash.jpg'
#     # filename = secure_filename(file.filename)

#     buckets = storage_client.list_buckets()
#     bucket = buckets[0]
#     return bucket.upload(filename, file)