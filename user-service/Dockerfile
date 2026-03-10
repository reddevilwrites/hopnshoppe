# Pre-built JAR Dockerfile — build the reactor from the repo root first:
#   mvn clean install -DskipTests
# Then: docker compose build user-service
FROM eclipse-temurin:17-jre-jammy
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
WORKDIR /app
COPY target/*.jar app.jar
RUN chown appuser:appgroup app.jar
USER appuser
EXPOSE 8084
ENTRYPOINT ["java", "-jar", "app.jar"]
