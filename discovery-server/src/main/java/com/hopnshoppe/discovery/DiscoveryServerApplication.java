package com.hopnshoppe.discovery;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.netflix.eureka.server.EnableEurekaServer;

/**
 * Eureka service registry for the HopNShoppe microservice platform.
 *
 * <p>All other services (auth-service, user-service, cart-service, catalog-service,
 * api-gateway) register with this server on startup and send periodic heartbeats.
 * The gateway resolves {@code lb://service-name} URIs by querying this registry.
 *
 * <p>Dashboard available at {@code http://localhost:8761} when running locally.
 */
@SpringBootApplication
@EnableEurekaServer
public class DiscoveryServerApplication {

    public static void main(String[] args) {
        SpringApplication.run(DiscoveryServerApplication.class, args);
    }
}
