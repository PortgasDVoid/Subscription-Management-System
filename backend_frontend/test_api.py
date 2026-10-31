import os
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_api_root():
    r=client.get('/')
    assert r.status_code==200 and r.json()['name'].startswith('Brightloop')

def test_variant_price_endpoint():
    r=client.post('/api/calculations/variant-price',json={'base_price':1000,'extra_price':560})
    assert r.status_code==200 and r.json()['unit_price']=='1560.00'

def test_line_calculation_endpoint():
    r=client.post('/api/calculations/line',json={'unit_price':1000,'quantity':2,'tax_rate':18,'discount':100})
    assert r.status_code==200 and r.json()['total']=='2242.00'

def test_invalid_line_rejected():
    r=client.post('/api/calculations/line',json={'unit_price':1000,'quantity':0,'tax_rate':18,'discount':0})
    assert r.status_code==422
