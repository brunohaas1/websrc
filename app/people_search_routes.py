from flask import Blueprint, request, jsonify, current_app
from .people_search_cache import cached_search
import time

people_search_bp = Blueprint('people_search', __name__)

# Simple in-memory rate limit per IP (window seconds, max requests)
_RATE_STATE = {}
RATE_WINDOW = 60
RATE_MAX = 10


def _is_rate_limited(ip: str) -> bool:
    now = int(time.time())
    entry = _RATE_STATE.get(ip)
    if not entry:
        _RATE_STATE[ip] = [now, 1]
        return False
    ts, count = entry
    if now - ts > RATE_WINDOW:
        _RATE_STATE[ip] = [now, 1]
        return False
    if count >= RATE_MAX:
        return True
    entry[1] = count + 1
    return False


@people_search_bp.route('/api/people_search', methods=['POST'])
def people_search():
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    if not name:
        return jsonify({'error': 'Nome não informado'}), 400

    ip = request.remote_addr or 'anonymous'
    if _is_rate_limited(ip):
        return jsonify({'error': 'Rate limit exceeded'}), 429

    results = cached_search(name)
    return jsonify(results)
