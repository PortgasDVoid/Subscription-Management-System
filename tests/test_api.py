import os
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
from fastapi.testclient import TestClient
from app.main import app
from app.auth import make_token

client = TestClient(app)


def test_api_root():
    r = client.get('/')
    assert r.status_code == 200 and r.json()['name'].startswith('Brightloop')

def test_variant_price_endpoint():       # brief example: a brand variant adds 560
    r = client.post('/api/calculations/variant-price', json={'base_price': 1000, 'extra_price': 560})
    assert r.status_code == 200 and r.json()['unit_price'] == '1560.00'

def test_line_calculation_endpoint():
    r = client.post('/api/calculations/line', json={'unit_price': 1000, 'quantity': 2, 'tax_rate': 18, 'discount': 100})
    assert r.status_code == 200 and r.json()['total'] == '2242.00'

def test_invalid_line_rejected():
    assert client.post('/api/calculations/line', json={'unit_price': 1000, 'quantity': 0, 'tax_rate': 18, 'discount': 0}).status_code == 422

def test_protected_endpoints_require_a_token():
    for method, path in [('get', '/api/resources/customers'), ('delete', '/api/resources/customers/1'), ('post', '/api/billing/run'),
                         ('get', '/api/dashboard/summary'), ('get', '/api/invoices/1/pdf'), ('get', '/api/portal/invoices'), ('post', '/api/payments')]:
        assert getattr(client, method)(path).status_code == 401, path

def test_garbage_and_expired_tokens_rejected():
    assert client.get('/api/resources/customers', headers={'Authorization': 'Bearer nope'}).status_code == 401
    assert client.get('/api/resources/customers', headers={'Authorization': 'Bearer ' + make_token(1, 'admin', ttl=-1)}).status_code == 401

def test_weak_password_rejected_before_touching_the_database():
    r = client.post('/api/auth/signup', json={'email': 'a@b.co', 'password': 'short', 'full_name': 'A'})
    assert r.status_code == 422 and 'Password' in r.json()['detail']
    r = client.post('/api/auth/reset-password', json={'token': 'x', 'new_password': 'alllowercase1'})
    assert r.status_code == 422
