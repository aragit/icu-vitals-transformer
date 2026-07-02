# Multi-stage build for production
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY src/ ./src/
COPY pyproject.toml .
COPY README.md .

ENV PATH=/root/.local/bin:/home/mobius/icu-vitals-transformer/.venv/bin:/run/user/1000/fnm_multishells/12430_1782973590608/bin:/home/mobius/.local/share/fnm:/run/user/1000/fnm_multishells/12427_1782973590566/bin:/home/mobius/.local/share/fnm:/run/user/1000/fnm_multishells/12424_1782973590526/bin:/home/mobius/.local/share/fnm:/home/mobius/gems/bin:/home/mobius/.nvm/versions/node/v20.18.3/bin:/home/mobius/gems/bin:/home/mobius/gems/bin:/home/mobius/anaconda3/bin:/home/mobius/anaconda3/condabin:/home/mobius/.local/bin:/home/mobius/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin:/snap/bin:/home/mobius/.lmstudio/bin:/home/mobius/.lmstudio/bin
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
