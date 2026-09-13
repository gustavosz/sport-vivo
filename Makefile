# ==============================================================================
# SPORT-VIVO: Makefile de Operaciones
# ==============================================================================
.PHONY: help up down restart logs status provision

help:
	@echo "⚽ Comandos disponibles para Sport-Vivo:"
	@echo "  make up         - Iniciar y aprovisionar el stack (Dispatcharr + Canales + EPG)"
	@echo "  make down       - Detener el stack limpiamente"
	@echo "  make restart    - Reiniciar el stack"
	@echo "  make logs       - Ver logs en vivo de Dispatcharr"
	@echo "  make status     - Ver estado del contenedor y servicios"
	@echo "  make provision  - Re-ejecutar aprovisionamiento de canales y EPG"

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
		-e PROVIDER_SERVER_URL="$$PROVIDER_SERVER_URL" \
		-e PROVIDER_USERNAME="$$PROVIDER_USERNAME" \
		-e PROVIDER_PASSWORD="$$PROVIDER_PASSWORD" \
		-e PROVIDER_MAX_STREAMS="$$PROVIDER_MAX_STREAMS" \
		-e EPG_NAME="$$EPG_NAME" \
		-e EPG_URL="$$EPG_URL" \
		dispatcharr su - dispatch -c "cd /app && python -" < scripts/provision.py
