FROM node:22-trixie

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bubblewrap build-essential ca-certificates clang cmake curl git jq \
        libseccomp-dev libssl-dev pkg-config python3 python3-venv tini \
        util-linux unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR=/usr/local/bin sh
RUN npm install --global \
        opencode-ai \
        @roberttlange/headless@0.6.1

# Pin ShinkaEvolve to the exact source revision used to build this adapter.
# Debian Trixie marks its system interpreter as externally managed, so keep
# the harness dependencies in a dedicated virtual environment.
RUN python3 -m venv /opt/shinka/venv \
    && uv pip install --python /opt/shinka/venv/bin/python \
        "git+https://github.com/SakanaAI/ShinkaEvolve.git@9912af12d423504b8d580f4179fd15f5f88b8c50"

RUN useradd --create-home --shell /bin/bash runner

WORKDIR /workspace
COPY . /workspace
COPY deploy/render/shinka-flock/entrypoint.sh /usr/local/bin/shinka-flock-entrypoint
COPY deploy/render/shinka-flock/research.sh /usr/local/bin/shinka-flock-research
COPY deploy/render/shinka-flock/submit-probe.sh /usr/local/bin/shinka-flock-submit-probe
COPY deploy/render/shinka-flock/opencode-max.sh /opt/shinka/bin/opencode
RUN cc -O2 -std=c11 -Wall -Wextra -Werror \
        deploy/render/shinka-flock/render-bwrap.c -lseccomp -o /usr/bin/bwrap \
    && /usr/bin/bwrap --version
RUN chmod 0755 \
        /usr/local/bin/shinka-flock-entrypoint \
        /usr/local/bin/shinka-flock-research \
        /usr/local/bin/shinka-flock-submit-probe \
        /opt/shinka/bin/opencode \
    && chown -R runner:runner /workspace

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/shinka-flock-entrypoint"]
