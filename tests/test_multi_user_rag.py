import pytest
from moviebot.core.conversational_rag import mask_pii, _check_privacy_and_intent

def test_mask_pii_no_known_users():
    text = "What did John watch?"
    assert mask_pii(text, {}, "111") == text

def test_mask_pii_masks_other_users():
    known_users = {
        "John": "123",
        "Alice": "456",
        "Bob_Nickname": "789"
    }
    
    # Simple mention of John (replaces the longest name, John, with <User_1>)
    text1 = "Did John like the movie?"
    assert mask_pii(text1, known_users, "456") == "Did <User_1> like the movie?"
    
    # Discord mention matching digits
    text2 = "What has <@789> seen?"
    assert mask_pii(text2, known_users, "456") == "What has <User> seen?"
    
    # Both Name and Discord mention
    text3 = "Alice and <@123>"
    assert mask_pii(text3, known_users, "789") == "<User_1> and <User>"

def test_mask_pii_does_not_mask_asking_user():
    known_users = {"Alice": "456"}
    text = "Did Alice like the movie?"
    # If the asker is Alice, her name should not be masked as it represents self
    assert mask_pii(text, known_users, "456") == text

def test_check_privacy_and_intent_allow():
    known_users = {"Alice": "456", "Bob": "789"}
    
    # General question
    assert _check_privacy_and_intent("What is a good sci-fi movie?", known_users, "456") == {"action": "allow"}
    
    # Mentions oneself
    assert _check_privacy_and_intent("What did Alice watch?", known_users, "456") == {"action": "allow"}

def test_check_privacy_and_intent_block_history():
    known_users = {"Alice": "456", "Bob": "789"}
    
    # Asking about Bob's history
    result1 = _check_privacy_and_intent("What did Bob watch last night?", known_users, "456")
    assert result1 == {"action": "block"}
    
    result2 = _check_privacy_and_intent("Has <@789> seen Avatar?", known_users, "456")
    assert result2 == {"action": "block"}
    
    result3 = _check_privacy_and_intent("Show me Bob's history", known_users, "456")
    assert result3 == {"action": "block"}

def test_check_privacy_and_intent_require_consent():
    known_users = {"Alice": "456", "Bob": "789"}
    
    # Asking for a joint recommendation
    result1 = _check_privacy_and_intent("Recommend a movie for me and Bob", known_users, "456")
    assert result1 == {"action": "require_consent", "target_user_id": "789"}
    
    result2 = _check_privacy_and_intent("Suggest something for us, <@789>", known_users, "456")
    assert result2 == {"action": "require_consent", "target_user_id": "789"}
