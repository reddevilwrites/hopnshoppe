package com.hopnshoppe.auth.service;

import com.hopnshoppe.auth.client.UserServiceFeignClient;
import com.hopnshoppe.common.dto.UserDTO;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Thin adapter that wraps the Feign call to user-service in a Resilience4j circuit breaker.
 *
 * <h2>Why a separate component?</h2>
 * Spring AOP (used by Resilience4j's {@code @CircuitBreaker}) only intercepts calls that
 * cross a bean boundary. If {@code AuthService} called its own {@code @CircuitBreaker}
 * method directly (self-invocation), the proxy would be bypassed and the circuit breaker
 * would never trip. Extracting the Feign call here into its own Spring bean guarantees
 * the proxy is always in the call path.
 *
 * <h2>Resilience behaviour</h2>
 * <pre>
 *   Normal:  user-service is up   → returns "John Doe"
 *   Degraded: user-service is slow / erroring → circuit opens after failure-rate-threshold
 *   Open:    fallback fires immediately       → returns email as display name
 *   Half-open: probes user-service            → closes if calls succeed again
 * </pre>
 *
 * Configure thresholds in {@code application.yml} under
 * {@code resilience4j.circuitbreaker.instances.user-service}.
 */
@Component
public class UserDisplayAdapter {

    private static final Logger log = LoggerFactory.getLogger(UserDisplayAdapter.class);

    private final UserServiceFeignClient feignClient;

    public UserDisplayAdapter(UserServiceFeignClient feignClient) {
        this.feignClient = feignClient;
    }

    /**
     * Fetches the user's full name. Protected by a circuit breaker named "user-service".
     *
     * @param email the JWT subject / login email
     * @return "firstName lastName" on success, email address on fallback
     */
    @CircuitBreaker(name = "user-service", fallbackMethod = "displayNameFallback")
    public String getDisplayName(String email) {
        UserDTO user = feignClient.getUserByEmail(email);
        return user.getFirstName() + " " + user.getLastName();
    }

    /**
     * Creates a user profile in user-service during signup.
     * If user-service is down, the ConflictException from {@code AuthService.signup}
     * propagates and the caller receives a 503 — both sides of the signup are atomic.
     */
    @CircuitBreaker(name = "user-service")
    public UserDTO createProfile(UserDTO dto) {
        return feignClient.createProfile(dto);
    }

    // -------------------------------------------------------------------------
    // Fallback methods — must match the signature of the primary method
    //                    plus an Exception (or Throwable) parameter at the end.
    // -------------------------------------------------------------------------

    /** Graceful degradation: login still succeeds even if user-service is down. */
    @SuppressWarnings("unused")
    private String displayNameFallback(String email, Exception ex) {
        log.warn("user-service circuit breaker OPEN — using email as display name for {}: {}",
                email, ex.getMessage());
        return email;
    }
}
