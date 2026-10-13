#!/usr/bin/env bash
# Migrate an empty database to the pre-artwork schema, insert logo stock, then
# migrate forward. Drops only the temporary database popmes_upgrade.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T database sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS popmes_upgrade;" -c "CREATE DATABASE popmes_upgrade;"'
docker compose exec -T -e POSTGRES_DB=popmes_upgrade backend python manage.py migrate core 0011 --noinput
docker compose exec -T database sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d popmes_upgrade' <<'SQL'
INSERT INTO core_product (code, name, instruction, color, active)
VALUES ('UP', 'Upgrade', '', '#cf8c38', true);
INSERT INTO core_variant (product_id, sku, name, weight_g, packaging, custom_label, instruction, active)
SELECT id, 'UP-30-LOGO', 'Upgrade z logo', 30, 'Doypack kraft', true, '', true
FROM core_product WHERE code = 'UP';
INSERT INTO core_stockitem (code, name, "group", unit, quantity, reserved, position, variant_id)
SELECT 'POP-UP-30-LOGO', 'Upgrade z logo', 'popcorn', 'szt', 4, 1, 0, id
FROM core_variant WHERE sku = 'UP-30-LOGO';
SQL
docker compose exec -T -e POSTGRES_DB=popmes_upgrade backend python manage.py migrate --noinput
docker compose exec -T -e POSTGRES_DB=popmes_upgrade backend python manage.py shell -c "from core.models import StockItem; row = StockItem.objects.get(artwork_unknown=True); assert (row.quantity, row.reserved) == (4, 1); plain = StockItem.objects.get(variant=row.variant, artwork_unknown=False, artwork_sha256=''); assert plain.quantity == 0; assert plain.code != row.code; print('schema upgrade kept the logo balance')"
docker compose exec -T database sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE popmes_upgrade;"'
