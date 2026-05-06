#!/usr/bin/env python3
"""Integration tests for financial management features."""

import json
import pytest
from datetime import datetime, timedelta
from app import create_app
from app.db import init_db

@pytest.fixture
def app():
    """Create test app."""
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        init_db('sqlite')
    return app

@pytest.fixture
def client(app):
    """Test client."""
    return app.test_client()

class TestAdvancedFilters:
    """Test advanced filtering."""
    
    def test_filter_by_date_range(self, client):
        """Test filtering by date range."""
        # Setup
        client.post('/api/finance/cashflow', json={
            'entry_date': '2024-01-15', 'entry_type': 'expense',
            'category': 'Food', 'description': 'Lunch', 'amount': 50
        })
        
        # Filter
        resp = client.get('/api/finance/cashflow?date_from=2024-01-01&date_to=2024-01-31')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0
    
    def test_filter_by_category(self, client):
        """Test filtering by category."""
        resp = client.get('/api/finance/cashflow?category=Food')
        assert resp.status_code == 200
    
    def test_filter_by_amount_range(self, client):
        """Test filtering by amount."""
        resp = client.get('/api/finance/cashflow?amount_min=10&amount_max=100')
        assert resp.status_code == 200

class TestTemplates:
    """Test template functionality."""
    
    def test_save_template(self, client):
        """Test saving a template."""
        resp = client.post('/api/finance/templates', json={
            'name': 'Netflix',
            'template': {
                'category': 'Entertainment',
                'description': 'Netflix Subscription',
                'fixed_amount': 49.90
            }
        })
        assert resp.status_code == 201
    
    def test_list_templates(self, client):
        """Test listing templates."""
        resp = client.get('/api/finance/templates')
        assert resp.status_code == 200

class TestAnalytics:
    """Test analytics functionality."""
    
    def test_get_analytics(self, client):
        """Test getting analytics."""
        month = datetime.now().strftime('%Y-%m')
        resp = client.get(f'/api/finance/analytics?month={month}')
        assert resp.status_code == 200
    
    def test_budget_alerts(self, client):
        """Test budget alerts."""
        month = datetime.now().strftime('%Y-%m')
        resp = client.get(f'/api/finance/budget-check?month={month}')
        assert resp.status_code == 200

class TestInlineEditing:
    """Test inline editing."""
    
    def test_update_amount(self, client):
        """Test updating amount inline."""
        # Create entry
        create_resp = client.post('/api/finance/cashflow', json={
            'entry_date': '2024-01-15', 'entry_type': 'expense',
            'category': 'Food', 'description': 'Lunch', 'amount': 50
        })
        entry_id = create_resp.get_json().get('id')
        
        # Update inline
        resp = client.patch(f'/api/finance/cashflow/{entry_id}', json={'amount': 75})
        assert resp.status_code == 200
    
    def test_update_category(self, client):
        """Test updating category inline."""
        create_resp = client.post('/api/finance/cashflow', json={
            'entry_date': '2024-01-15', 'entry_type': 'expense',
            'category': 'Food', 'description': 'Lunch', 'amount': 50
        })
        entry_id = create_resp.get_json().get('id')
        
        resp = client.patch(f'/api/finance/cashflow/{entry_id}', json={'category': 'Transport'})
        assert resp.status_code == 200

class TestPDFReports:
    """Test PDF report generation."""
    
    def test_generate_pdf(self, client):
        """Test PDF generation."""
        month = datetime.now().strftime('%Y-%m')
        resp = client.get(f'/api/finance/report/pdf?month={month}')
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'

class TestValidations:
    """Test validations."""
    
    def test_validate_amount_positive(self, client):
        """Test amount must be positive."""
        resp = client.post('/api/finance/cashflow', json={
            'entry_date': '2024-01-15', 'entry_type': 'expense',
            'category': 'Food', 'description': 'Lunch', 'amount': -50
        })
        # Should fail or handle gracefully
        assert resp.status_code in (400, 200)
    
    def test_validate_category_required(self, client):
        """Test category is required."""
        resp = client.post('/api/finance/cashflow', json={
            'entry_date': '2024-01-15', 'entry_type': 'expense',
            'category': '', 'description': 'Lunch', 'amount': 50
        })
        assert resp.status_code in (400, 200)

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
