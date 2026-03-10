package com.hopnshoppe.auth;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.cloud.openfeign.EnableFeignClients;

/**
 * HopNShoppe Auth Service.
 *
 * <p>Single responsibility: manage credentials and issue JWTs.
 * Profile data is delegated to user-service via the Feign client.
 *
 * <p>{@code @EnableFeignClients} scans this package for {@code @FeignClient}
 * interfaces and registers them as Spring beans. The {@code UserServiceFeignClient}
 * is discovered via Eureka ({@code lb://user-service}) and wrapped in a
 * Resilience4j circuit breaker via {@code UserDisplayAdapter}.
 */
@SpringBootApplication
@EnableDiscoveryClient
@EnableFeignClients
public class AuthServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(AuthServiceApplication.class, args);
    }
}
