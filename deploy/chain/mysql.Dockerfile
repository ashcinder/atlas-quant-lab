ARG ATLAS_MYSQL_BASE_IMAGE=mysql:8.4@sha256:a0225d1ea6631c8bc2385dc4c2faba17bbf1834ecf369e1659a9a382bd8d5dd7
FROM ${ATLAS_MYSQL_BASE_IMAGE}
LABEL org.atlas.component="isolated-lab-mysql"
