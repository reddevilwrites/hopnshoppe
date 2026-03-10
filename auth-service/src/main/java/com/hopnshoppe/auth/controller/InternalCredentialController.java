package com.hopnshoppe.auth.controller;

import com.hopnshoppe.auth.repository.CredentialRepository;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

/**
 * Service-internal API for credential management.
 *
 * <p>Not exposed through the API gateway — only reachable within the Docker/k8s network.
 * Currently used by the Playwright E2E test teardown to delete test accounts created
 * during test runs.
 *
 * <h2>Production hardening (TODO)</h2>
 * Protect with mTLS or a shared internal API key header before exposing beyond localhost.
 */
@RestController
@RequestMapping("/internal/credentials")
public class InternalCredentialController {

    private final CredentialRepository credentialRepository;

    public InternalCredentialController(CredentialRepository credentialRepository) {
        this.credentialRepository = credentialRepository;
    }

    /**
     * Deletes the credential record for the given email.
     * Returns 204 No Content whether or not the record existed.
     */
    @DeleteMapping("/{email}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @Transactional
    public void deleteCredential(@PathVariable String email) {
        credentialRepository.deleteByEmail(email);
    }
}
