from flask import Blueprint, request, jsonify
from .people_search_cache import cached_search

people_search_bp = Blueprint('people_search', __name__)

@people_search_bp.route('/api/people_search', methods=['POST'])
def people_search():
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({'error': 'Nome não informado'}), 400
    results = cached_search(name)
    return jsonify(results)
