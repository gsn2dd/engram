# All-in-one: Postgres+pgvector with the engram schema and brain library baked
# in. `docker run` alone gives you a working agent-brain, no separate DB setup.
# working pretrained model, no separate database container/setup needed.
FROM pgvector/pgvector:pg16

ENV POSTGRES_DB=pathmemoria \
    POSTGRES_USER=pathuser \
    POSTGRES_PASSWORD=pathpass \
    PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .
COPY schema.sql /docker-entrypoint-initdb.d/schema.sql
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080 5432
ENTRYPOINT ["/entrypoint.sh"]
