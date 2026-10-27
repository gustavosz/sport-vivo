# ==============================================================================
# SPORT-VIVO: Makefile de Operaciones
# ==============================================================================
.PHONY: help up down restart logs status provision audit ranking match river boca validate-ip daily-sync setup-cron daemon-status daemon-logs daemon-restart test

help:
	@echo "⚽ Comandos disponibles para Sport-Vivo:"
	@echo "  make up             - Iniciar y aprovisionar el stack + Stream Watcher Daemon"
	@echo "  make down           - Detener el stack limpiamente"
	@echo "  make restart        - Reiniciar el stack"
	@echo "  make logs           - Ver logs en vivo de Dispatcharr"
	@echo "  make status         - Ver estado del contenedor y servicios"
	@echo "  make daemon-status  - Ver estado del Stream Watcher Daemon (bitrate, canal activo)"
	@echo "  make daemon-logs    - Ver logs en vivo del Stream Watcher Daemon"
	@echo "  make daemon-restart - Reiniciar el Stream Watcher Daemon"
	@echo "  make provision      - Re-ejecutar aprovisionamiento de canales y EPG"
	@echo "  make match          - Forzar ya la sincronización de partidos (Canal 17 AFA Play / 18 Internacional)"
	@echo "  make river          - Igual que match, solo River Plate"
	@echo "  make boca           - Igual que match, solo Boca Juniors"
	@echo "  make validate-ip    - Verificar y sincronizar IP local de la Mac en .env"
	@echo "  make daily-sync     - Ejecutar ciclo diario de sincronización y salud de cuenta"
	@echo "  make setup-cron     - Instalar tarea programada diaria (cron) en macOS"
	@echo "  make audit          - Auditar calidad del proveedor en vivo y calcular score"
	@echo "  make ranking        - Ver tabla histórica y top de proveedores evaluados"
	@echo "  make test           - Ejecutar suite de tests unitarios (tests/)"

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
		dispatcharr su dispatch -c "cd /app && python -" < src/provision.py

audit:
	@test -f .env || { echo "❌ Falta archivo .env"; exit 1; }
	@set -a; . ./.env; set +a; \
	SELLER="$${SELLER:-$$PROVIDER_SELLER}"; \
	docker exec -i \
		dispatcharr su - dispatch -c "cd /app && EVAL_MODE=audit CLIENT_USERNAME=$$CLIENT_USERNAME CLIENT_PASSWORD=$$CLIENT_PASSWORD DISPATCHARR_PORT=$${DISPATCHARR_PORT:-9191} PROVIDER_NAME=\"$$PROVIDER_NAME\" PROVIDER_USERNAME=\"$$PROVIDER_USERNAME\" PROVIDER_SELLER=\"$$SELLER\" python -" < src/evaluate_provider.py

ranking:
	@docker exec -i dispatcharr su - dispatch -c "cd /app && EVAL_MODE=ranking python -" < src/evaluate_provider.py

match:
	@test -f .env || { echo "❌ Falta archivo .env"; exit 1; }
	@set -a; . ./.env; set +a; \
	docker exec -i \
		-e PROVIDER_USERNAME="$$PROVIDER_USERNAME" \
		dispatcharr su dispatch -c "cd /app && python - --team $${TEAM:-auto}" < src/sync_match.py

river:
	@test -f .env || { echo "❌ Falta archivo .env"; exit 1; }
	@set -a; . ./.env; set +a; \
	docker exec -i \
		-e PROVIDER_USERNAME="$$PROVIDER_USERNAME" \
		dispatcharr su dispatch -c "cd /app && python - --team river" < src/sync_match.py

boca:
	@test -f .env || { echo "❌ Falta archivo .env"; exit 1; }
	@set -a; . ./.env; set +a; \
	docker exec -i \
		-e PROVIDER_USERNAME="$$PROVIDER_USERNAME" \
		dispatcharr su dispatch -c "cd /app && python - --team boca" < src/sync_match.py

validate-ip:
	@chmod +x scripts/*.sh
	@./scripts/validate_ip.sh

daily-sync:
	@chmod +x scripts/*.sh
	@./scripts/daily_sync.sh

setup-cron:
	@chmod +x scripts/*.sh
	@./scripts/setup_cron.sh

daemon-status:
	@bash scripts/daemon.sh status

daemon-logs:
	@tail -f -n 50 logs/stream_daemon.log

daemon-restart:
	@echo "🔄 Reiniciando Sport-Vivo Stream Watcher Daemon..."
	@bash scripts/daemon.sh restart
	@bash scripts/daemon.sh status

test:
	@echo "🧪 Ejecutando suite de tests unitarios (tests/)..."
	@docker exec -u dispatch -w /app -e PYTHONDONTWRITEBYTECODE=1 -e SPORT_VIVO_LOG_DIR=/tmp dispatcharr python3 -m unittest discover -s /app/tests -p "test_*.py" -v

