# Student Information Mapping
# Add your student information here
# Format: student_id: {name, gender}

STUDENT_INFO = {
    "B02052437": {
        "first_name": "Raman",
        "middle_name": "Muayad",
        "last_name": "Lateef",
        "gender": "Male"
    },
    "B02052324": {
        "first_name": "Emad",
        "middle_name": "",
        "last_name": "",
        "gender": "Male"
    },
    "76da9aa1-6896-41f1-85fe-1a5173c7ca1": {
        "first_name": "Slava",
        "middle_name": "Jamil",
        "last_name": "Mahmood",
        "gender": "Female"
    }
}

def get_student_info(student_id: str):
    """Get student information by ID"""
    info = STUDENT_INFO.get(student_id)
    
    if info:
        # Return info from mapping
        return info
    else:
        # Fallback: Use student ID as the name
        return {
            "first_name": student_id,  # Use full student ID as name
            "middle_name": "",
            "last_name": "",
            "gender": "Male"  # Default to Male (can be updated later)
        }
