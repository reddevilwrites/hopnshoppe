package com.hopnshoppe.user.service;

import com.hopnshoppe.common.dto.UserDTO;
import com.hopnshoppe.common.exception.ConflictException;
import com.hopnshoppe.common.exception.ResourceNotFoundException;
import com.hopnshoppe.user.dto.UpdateProfileRequest;
import com.hopnshoppe.user.model.UserProfile;
import com.hopnshoppe.user.repository.UserProfileRepository;
import jakarta.transaction.Transactional;
import org.springframework.stereotype.Service;

@Service
public class UserProfileService {

    private final UserProfileRepository repository;

    public UserProfileService(UserProfileRepository repository) {
        this.repository = repository;
    }

    /**
     * Returns profile data for the public GET /users/{id} endpoint.
     * Uses the shared {@link UserDTO} from common-library so the response shape
     * is consistent across services.
     */
    public UserDTO getById(Long id) {
        UserProfile profile = repository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("User not found with id: " + id));
        return toDTO(profile);
    }

    /**
     * Returns the authenticated user's own profile (GET /account/me).
     * The email is extracted from the validated JWT subject by the caller.
     */
    public UserDTO getByEmail(String email) {
        UserProfile profile = repository.findByEmail(email)
                .orElseThrow(() -> new ResourceNotFoundException("User not found: " + email));
        return toDTO(profile);
    }

    /**
     * Updates mutable profile fields (PUT /account/me).
     * Migrated from monolith's UserService.updateUserProfile().
     */
    @Transactional
    public UserDTO updateProfile(String email, UpdateProfileRequest request) {
        UserProfile profile = repository.findByEmail(email)
                .orElseThrow(() -> new ResourceNotFoundException("User not found: " + email));

        profile.setEmail(request.getEmail());
        profile.setFirstName(request.getFirstName());
        profile.setLastName(request.getLastName());
        profile.setPhone(request.getPhone());

        return toDTO(repository.save(profile));
    }

    /**
     * Creates a new profile record. Called by auth-service via the internal API
     * during user signup — never invoked from public-facing controllers.
     *
     * <p>Throws {@link ConflictException} (→ HTTP 409) if the email already exists,
     * which triggers auth-service to roll back the credential it just created.
     */
    @Transactional
    public UserDTO createProfile(UserDTO dto) {
        if (repository.existsByEmail(dto.getEmail())) {
            throw new ConflictException("Profile already exists for email: " + dto.getEmail());
        }

        UserProfile profile = new UserProfile();
        profile.setEmail(dto.getEmail());
        profile.setFirstName(dto.getFirstName());
        profile.setLastName(dto.getLastName());
        profile.setPhone(dto.getPhone());

        return toDTO(repository.save(profile));
    }

    /**
     * Deletes a profile by email. Called by the internal test-cleanup endpoint.
     * Silently succeeds if the profile does not exist.
     */
    @Transactional
    public void deleteByEmail(String email) {
        repository.deleteByEmail(email);
    }

    // -------------------------------------------------------------------------

    private UserDTO toDTO(UserProfile p) {
        return UserDTO.builder()
                .email(p.getEmail())
                .firstName(p.getFirstName())
                .lastName(p.getLastName())
                .phone(p.getPhone())
                .build();
    }
}
