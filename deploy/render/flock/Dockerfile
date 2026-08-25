FROM node:22-trixie

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates clang cmake curl git jq \
        libssl-dev pkg-config python3 python3-venv tini util-linux unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR=/usr/local/bin sh
RUN npm install --global opencode-ai

RUN useradd --create-home --shell /bin/bash runner

WORKDIR /workspace
COPY . /workspace
COPY deploy/render/flock/entrypoint.sh /usr/local/bin/flock-entrypoint
COPY deploy/render/flock/research.sh /usr/local/bin/flock-research
COPY deploy/render/flock/submit-probe.sh /usr/local/bin/flock-submit-probe
RUN chmod 0755 \
        /usr/local/bin/flock-entrypoint \
        /usr/local/bin/flock-research \
        /usr/local/bin/flock-submit-probe \
    && chown -R runner:runner /workspace

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/flock-entrypoint"]
