package com.wknd.spring.client.config_client.service;

import java.util.HashMap;
import java.util.Map;

import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import com.wknd.spring.client.config_client.dto.SignupRequest;
import com.wknd.spring.client.config_client.dto.UpdateProfileDTO;
import com.wknd.spring.client.config_client.dto.UserProfileDTO;
import com.wknd.spring.client.config_client.model.User;
import com.wknd.spring.client.config_client.repository.UserRepository;

import jakarta.transaction.Transactional;

@Service
public class UserService {
    private final Map<String, String> users = new HashMap<>();
    private final UserRepository userRepository;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    @Transactional
    public User signup(SignupRequest signupRequest){
        if(userRepository.existsByEmail(signupRequest.getEmail())){
            throw new IllegalArgumentException("Email already in use");
        }

        User user = new User();
        user.setEmail(signupRequest.getEmail());
        user.setFirstName(signupRequest.getFirstName());
        user.setLastName(signupRequest.getLastName());
        user.setPhone(signupRequest.getPhone());
        user.setPassword(passwordEncoder.encode(signupRequest.getPassword()));
        return userRepository.save(user);
    }

    public boolean authenticate(String username, String password){
        return userRepository.existsByEmail(username) && passwordEncoder.matches(password, userRepository.findByEmail(username).getPassword());
    }

    public UserProfileDTO getUserProfile(String username){
        System.out.println("Looking for user: " + username);

        User currentUser = userRepository.findByEmail(username);
        UserProfileDTO userProfileDTO = new UserProfileDTO();
        userProfileDTO.setEmail(currentUser.getEmail());
        userProfileDTO.setFirstName(currentUser.getFirstName());
        userProfileDTO.setLastName(currentUser.getLastName());
        userProfileDTO.setPhone(currentUser.getPhone());
        return userProfileDTO;
    }

    @Transactional
    public UserProfileDTO updateUserProfile(String username, UpdateProfileDTO updateProfileDTO){
        User currentUser = userRepository.findByEmail(username);
        UserProfileDTO userProfileDTO = new UserProfileDTO();
        currentUser.setEmail(updateProfileDTO.getEmail());
        currentUser.setFirstName(updateProfileDTO.getFirstName());
        currentUser.setLastName(updateProfileDTO.getLastName());
        currentUser.setPhone(updateProfileDTO.getPhone());
        userRepository.save(currentUser);

        userProfileDTO.setEmail(updateProfileDTO.getEmail());
        userProfileDTO.setFirstName(updateProfileDTO.getFirstName());
        userProfileDTO.setLastName(updateProfileDTO.getLastName());
        userProfileDTO.setPhone(updateProfileDTO.getPhone());
        return userProfileDTO;
        
    }

    
}
