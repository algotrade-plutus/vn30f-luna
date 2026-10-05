FROM 943193395259.dkr.ecr.ap-southeast-1.amazonaws.com/algotrade-paper@sha256:d79e6a337705eb05c2ed1c20384cfeef12b9548b1ff94dd191b45c3e3dfbadb3

LABEL org.opencontainers.image.revision="recovered-ec2-20260924-74f9b42fbda8" \
      org.opencontainers.image.version="ec2-baseline-20260924-74f9b42fbda8" \
      io.algotrade.source-sha256="2b14a86b43f91ad4f40c60ff16bd414da5377801fa0c812899fa8f84a0852bcd"

COPY --chown=10001:10001 production-source/app/algotrade_adapter/safe_alpha.py /app/algotrade_adapter/safe_alpha.py
COPY --chown=10001:10001 production-source/app/alphas/master_unified/service.py /app/alphas/master_unified/service.py
COPY --chown=10001:10001 production-source/app/alphas/master_unified/genesis_engine.py /app/alphas/master_unified/genesis_engine.py
COPY --chown=10001:10001 production-source/app/alphas/master_unified/schedule.py /app/alphas/master_unified/schedule.py
COPY --chown=10001:10001 production-source/dashboard-app/dashboard/static/index.html /app/dashboard/static/index.html
COPY --chown=10001:10001 release-manifest.json /app/release.json
