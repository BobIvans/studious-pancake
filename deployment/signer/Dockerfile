ARG PYTHON_IMAGE=python:3.13.13-slim-bookworm
FROM ${PYTHON_IMAGE}

RUN groupadd --system --gid 65532 signer && \
    useradd --system --uid 65532 --gid signer --no-create-home signer
COPY isolated_signer_service /build/isolated_signer_service
RUN python -m pip install --no-cache-dir --no-deps /build/isolated_signer_service && \
    rm -rf /build /root/.cache

USER 65532:65532
WORKDIR /nonexistent
ENTRYPOINT ["flashloan-isolated-signer"]
CMD ["status", "--json"]
