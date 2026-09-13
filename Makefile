# ==============================================================================
# SPORT-VIVO: Makefile de Operaciones
# ==============================================================================
.PHONY: help up down restart logs status provision audit ranking

help:
	@echo "⚽ Comandos disponibles para Sport-Vivo:"
	@echo "  make up         - Iniciar y aprovisionar el stack (Dispatcharr + Canales + EPG)"
	@echo "  make down       - Detener el stack limpiamente"
	@echo "  make restart    - Reiniciar el stack"
	@echo "  make logs       - Ver logs en vivo de Dispatcharr"
	@echo "  make status     - Ver estado del contenedor y servicios"
	@echo "  make provision  - Re-ejecutar aprovisionamiento de canales y EPG"
	@echo "  make audit      - Auditar calidad del proveedor en vivo y calcular score"
	@echo "  make ranking    - Ver tabla histórica y top de proveedores evaluados"

up:
	@chmod +x scripts/*.sh
	@./scripts/start.sh

down:
	@chmod +x scripts/*.sh
	@./scripts/stop.sh

restart: down up

logs:
	docker compose logs -f --tail=100 dispatcharr

status:
	docker compose ps

provision:
	@test -f .env || { echo "❌ Falta archivo .env"; exit 1; }
	@set -a; . ./.env; set +a; \
	docker exec -i \
		-e ADMIN_USERNAME="$$ADMIN_USERNAME" \
		-e ADMIN_PASSWORD="$$ADMIN_PASSWORD" \
		-e CLIENT_USERNAME="$$CLIENT_USERNAME" \
		-e CLIENT_PASSWORD="$$CLIENT_PASSWORD" \
		-e PROVIDER_NAME="$$PROVIDER_NAME" \
		-e PROVIDER_SELLER="$$PROVIDER_SELLER" \
		-e PROVIDER_SERVER_URL="$$PROVIDER_SERVER_URL" \
		-e PROVIDER_USERNAME="$$PROVIDER_USERNAME" \
		-e PROVIDER_PASSWORD="$$PROVIDER_PASSWORD" \
		-e PROVIDER_MAX_STREAMS="$$PROVIDER_MAX_STREAMS" \
		-e BACKUP_PROVIDER_NAME="$$BACKUP_PROVIDER_NAME" \
		-e BACKUP_PROVIDER_SELLER="$$BACKUP_PROVIDER_SELLER" \
		-e BACKUP_PROVIDER_SERVER_URL="$$BACKUP_PROVIDER_SERVER_URL" \
		-e BACKUP_PROVIDER_USERNAME="$$BACKUP_PROVIDER_USERNAME" \
		-e BACKUP_PROVIDER_PASSWORD="$$BACKUP_PROVIDER_PASSWORD" \
		-e BACKUP_PROVIDER_MAX_STREAMS="$$BACKUP_PROVIDER_MAX_STREAMS" \
		-e EPG_NAME="$$EPG_NAME" \
		-e EPG_URL="$$EPG_URL" \
		dispatcharr su - dispatch -c "cd /app && python -" < scripts/provision.py

audit:
	@test -f .env || { echo "❌ Falta archivo .env"; exit 1; }
	@set -a; . ./.env; set +a; \
	SELLER="$${SELLER:-$$PROVIDER_SELLER}"; \
	docker exec -i \
		dispatcharr su - dispatch -c "cd /app && EVAL_MODE=audit CLIENT_USERNAME=$$CLIENT_USERNAME CLIENT_PASSWORD=$$CLIENT_PASSWORD DISPATCHARR_PORT=$${DISPATCHARR_PORT:-9191} PROVIDER_NAME=\"$$PROVIDER_NAME\" PROVIDER_USERNAME=\"$$PROVIDER_USERNAME\" PROVIDER_SELLER=\"$$SELLER\" python -" < scripts/evaluate_provider.py

ranking:
	@docker exec -i dispatcharr su - dispatch -c "cd /app && EVAL_MODE=ranking python -" < scripts/evaluate_provider.py
