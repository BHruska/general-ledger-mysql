# See all services; status, health, and uptime
cd /opt/apps/photon-docker-infra
docker-compose ps


# Follow Live Logs
docker-compose logs -f
docker-compose logs -f market-dashboard
docker-compose logs -f trade-dashboard
docker-compose logs -f nginx
docker-compose logs -f db


# View recent logs
docker-compose logs --tail=100 market-dashboard

# Search logs for errors:
docker-compose logs market-dashboard | grep -i error
docker-compose logs trade-dashboard | grep -i exception
docker-compose logs nginx | grep -i 'error'

# View all logs at same time
scripts/logs.sh all
