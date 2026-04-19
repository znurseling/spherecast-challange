#!/usr/bin/env bash
# Quick smoke tests for the Agnes API. Run after `uvicorn app.main:app --reload`.
# These are also the exact shapes the mobile app will send.
#

API=http://localhost:8000
KEY=${AGNES_API_KEY:-devkey}
H="X-API-Key: $KEY"

echo "--- health (no auth) ---"
curl -s $API/api/v1/health | python3 -m json.tool
echo

echo "--- top 5 consolidation candidates ---"
curl -s -H "$H" "$API/api/v1/candidates?limit=5" | python3 -m json.tool
echo

echo "--- product detail for id=200 ---"
curl -s -H "$H" $API/api/v1/products/200 | python3 -m json.tool
echo

echo "--- substitution: can 201 replace 200? (strict) ---"
curl -s -H "$H" -H "Content-Type: application/json" \
  -d '{"product_a_id": 200, "product_b_id": 201, "mode": "strict"}' \
  $API/api/v1/substitute | python3 -m json.tool
echo

echo "--- recommendation for product 200 (strict) ---"
curl -s -H "$H" -H "Content-Type: application/json" \
  -d '{"product_id": 200, "mode": "strict"}' \
  $API/api/v1/recommend | python3 -m json.tool
echo

echo "--- dashboard ---"
curl -s -H "$H" $API/api/v1/dashboard | python3 -m json.tool
