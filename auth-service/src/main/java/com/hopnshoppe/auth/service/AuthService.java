package com.hopnshoppe.auth.service;

import com.hopnshoppe.auth.dto.LoginResponse;
import com.hopnshoppe.auth.dto.SignupRequest;
import com.hopnshoppe.auth.model.Credential;
import com.hopnshoppe.auth.repository.CredentialRepository;
import com.hopnshoppe.auth.util.JwtUtil;
import com.hopnshoppe.common.dto.UserDTO;
import com.hopnshoppe.common.exception.ConflictException;
import jakarta.transaction.Transactional;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class AuthService {

    private final CredentialRepository credentialRepository;
    private final JwtUtil jwtUtil;
    private final BCryptPasswordEncoder passwordEncoder;
    private final UserDisplayAdapter userDisplayAdapter;

    public AuthService(CredentialRepository credentialRepository,
                       JwtUtil jwtUtil,
                       UserDisplayAdapter userDisplayAdapter) {
        this.credentialRepository = credentialRepository;
        this.jwtUtil = jwtUtil;
        this.passwordEncoder = new BCryptPasswordEncoder();
        this.userDisplayAdapter = userDisplayAdapter;
    }

    /**
     * Validates credentials and returns a JWT with the user's display name.
     *
     * <p>The display name is fetched from user-service via a Feign call wrapped in
     * a Resilience4j circuit breaker ({@link UserDisplayAdapter#getDisplayName}).
     * If user-service is down, login still succeeds — the displayName falls back
     * to the user's email address.
     *
     * @return {@link LoginResponse} on success, {@code null} if credentials are invalid
     *         (AuthController maps null → HTTP 401)
     */
    public LoginResponse login(String email, String password) {
        return credentialRepository.findByEmail(email)
                .filter(c -> passwordEncoder.matches(password, c.getPasswordHash()))
                .map(c -> {
                    String token = jwtUtil.generateToken(c.getEmail());
                    String displayName = userDisplayAdapter.getDisplayName(c.getEmail());
                    return new LoginResponse(token, displayName);
                })
                .orElse(null);
    }

    /**
     * Two-phase signup:
     * <ol>
     *   <li>Persist a credential record in auth_db.</li>
     *   <li>Call user-service via Feign to create the matching profile in user_db.</li>
     * </ol>
     *
     * <p>If user-service returns 409 (profile already exists) or is unreachable,
     * the {@code @Transactional} boundary rolls back the credential insert,
     * leaving both databases clean. This is the compensating transaction pattern.
     *
     * <p>Note: @Transactional only covers the local JPA write. The Feign call is
     * outside the local transaction. For full distributed consistency in production
     * consider the Saga pattern (event-driven or orchestrated).
     */
    @Transactional
    public void signup(SignupRequest request) {
        if (credentialRepository.existsByEmail(request.getEmail())) {
            throw new ConflictException("Email already registered: " + request.getEmail());
        }

        Credential credential = new Credential();
        credential.setEmail(request.getEmail());
        credential.setPasswordHash(passwordEncoder.encode(request.getPassword()));
        credentialRepository.save(credential);

        // Profile creation in user-service — if this throws, the transaction above rolls back.
        UserDTO profileRequest = UserDTO.builder()
                .email(request.getEmail())
                .firstName(request.getFirstName())
                .lastName(request.getLastName())
                .phone(request.getPhone())
                .build();

        userDisplayAdapter.createProfile(profileRequest);
    }
}
