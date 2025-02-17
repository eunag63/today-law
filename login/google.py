import os
import json
import requests
from flask import Blueprint, redirect, request, jsonify, make_response
from datetime import datetime, timedelta
import jwt
from oauthlib.oauth2 import WebApplicationClient
from pymongo import MongoClient

TOKEN_KEY = os.environ['TOKEN_KEY']

bp = Blueprint("google", __name__, url_prefix='/')

MONGO_URL = os.environ['MONGO_URL']
MONGO_USERNAME = os.environ['MONGO_USERNAME']
MONGO_PASSWORD = os.environ['MONGO_PASSWORD']
client = MongoClient(MONGO_URL, 27017, username=MONGO_USERNAME, password=MONGO_PASSWORD)
db = client.todaylaw

GOOGLE_CLIENT_ID = os.environ['Google_API']
GOOGLE_CLIENT_SECRET = os.environ['Google_SECRET']
jwt_secret = os.environ['JWT_SECRET']

GOOGLE_DISCOVERY_URL = (
    "https://accounts.google.com/.well-known/openid-configuration"
)

client = WebApplicationClient(GOOGLE_CLIENT_ID)

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


@bp.route("/oauth/google", methods=["GET"])
def login():
    google_provider_cfg = get_google_provider_cfg()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=request.base_url + "/callback",
        scope=["openid", "email", "profile"],
    )
    return redirect(request_uri)


@bp.route("/oauth/google/callback")
def callback():
    code = request.args.get("code")

    google_provider_cfg = get_google_provider_cfg()
    token_endpoint = google_provider_cfg["token_endpoint"]

    token_url, headers, body = client.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=request.base_url,
        code=code,
    )
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
    )
    client.parse_request_body_response(json.dumps(token_response.json()))
    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = client.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers, data=body)

    if userinfo_response.json().get("email_verified"):
        unique_id = userinfo_response.json()["sub"]
        users_email = userinfo_response.json()["email"]
        picture = userinfo_response.json()["picture"]
        users_name = userinfo_response.json()["given_name"]
    else:
        return "User email not available or not verified by Google.", 400


    find_user = db.users.find_one({'user_id': unique_id})
    if find_user is None:
        user_info_doc = {
            "user_id": unique_id,
            "username": users_email,
            "name": users_name,
            "profile_image": picture,
            "like_laws": [],
            "hate_laws": [],
            "bookmarks": [],
            "comments": [],
            "receive_mail": False,
            "bio":" ",
            "recently_view": []
        }

        db.users.insert_one(user_info_doc)

    return login(unique_id, users_name)


def login(id, name):
    # JWT 토큰 구성
    payload = {
        "user_id": id,
        "name": name,
        "exp": datetime.utcnow() + timedelta(seconds=60 * 60 * 24)
        # "exp": datetime.utcnow() + timedelta(seconds=60) # 테스트용으로 10초만 유효한 토큰 생성
    }

    # JWT 토큰 생성
    token = jwt.encode(payload, jwt_secret, algorithm='HS256')

    # 쿠키를 담은 response를 구성하기 위해 make_response 사용
    response = make_response(redirect('/'))
    # 쿠키에 토큰 세팅
    response.set_cookie(TOKEN_KEY, token)

    return response


@bp.route('/login-check')
def login_check():
    token = request.cookies.get(TOKEN_KEY)
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=['HS256'])

        user = db.users.find_one({'user_id': payload['user_id']}, {'_id': False})
        return jsonify({'result': 'success', 'name': user['name'], 'profile_image': user['profile_image']})
    except (jwt.ExpiredSignatureError, jwt.exceptions.DecodeError):
        return redirect('/')


def get_google_provider_cfg():
    return requests.get(GOOGLE_DISCOVERY_URL).json()
