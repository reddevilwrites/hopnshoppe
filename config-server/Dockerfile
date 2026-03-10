# ---- Build Stage ----
FROM maven:3.9.4-eclipse-temurin-17 AS build
WORKDIR /app
COPY . .
RUN mvn clean package -DskipTests

# ---- Run Stage ----
FROM eclipse-temurin:17-jre-jammy
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
WORKDIR /app

# Copy config repo folder
COPY --chown=appuser:appgroup config-repo /app/config-repo
COPY --from=build --chown=appuser:appgroup /app/target/config-server-0.0.1-SNAPSHOT.jar app.jar
USER appuser
EXPOSE 8888
ENTRYPOINT ["java", "-jar", "app.jar"]
