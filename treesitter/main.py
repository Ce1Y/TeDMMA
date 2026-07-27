import tree_sitter_java as tsjava
from tree_sitter import Language, Parser
import feature_capture as fc
import api_test_generate as atg
import asyncio
import text_processor
import json
import yaml

JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)

### ======== Target File ======== ###
TARGET_ZIP_FILE = "spring-petclinic-main"
### ======== Target File ======== ###

async def main():
    result = text_processor.load_java_project("migrate_project/" + TARGET_ZIP_FILE + ".zip") # get a list of language block from the target project zip file
    print("Load project completed. Total files loaded: ", len(result))
    
    prompt_features = ""    # feature prompt
    prompt_test_cases = "### Test Source Code ###\n" # test case prompt
    
    pure_text = ""
    
    for item in result:
        class_type = item[0]    
        code_content = item[1]  
        
        ### testing ###
        pure_text += code_content + "\n"
        
        if class_type == "TEST":
            prompt_test_cases += f"\n--- Test File ---\n{code_content}\n"
            continue 
        
        features = fc.extract_features(item)
        
        if features != None:
            if "class_name" in features:
                if features['component_type'] == "Controller":
                    prompt_features += "/*===Controller===*/\n" + str(features) + "\n\n"
                elif features['component_type'] == "Service":
                    prompt_features += "/*===Service===*/\n" + str(features) + "\n\n"
                else:
                    pass
            elif "entity_name" in features:
                prompt_features += "/*===Entity===*/\n" + str(features) + "\n\n"
            elif "repo_name" in features:
                prompt_features += "/*===Repository===*/\n" + str(features) + "\n\n"
            elif "dto_name" in features:
                prompt_features += "/*===DTO===*/\n" + str(features) + "\n\n"

    # with open("pure_text.txt", "w", encoding="utf-8") as f:
    #     f.write(pure_text)
    
    # Features prompt output
    with open(f"./monolith_features/{TARGET_ZIP_FILE}_features.txt", "w", encoding="utf-8") as f:
        f.write(prompt_features)
    print(">>> Feature extracted.")

    # Test cases prompt output
    with open(f"./monolith_test_case_codes/{TARGET_ZIP_FILE}_test_cases.txt", "w", encoding="utf-8") as f:
        f.write(prompt_test_cases)
    print(">>> Test case extracted.")
        
    # LLM analysis output
    # analysis_response = atg.analyze_ast_features(prompt_features)
    # with open(f"./llm_analysis_result/{TARGET_ZIP_FILE}_analysis_response.txt", "w", encoding="utf-8") as f:
    #     f.write(analysis_response)
    with open(f"./llm_analysis_result/{TARGET_ZIP_FILE}_analysis_response.txt", "r", encoding="utf-8") as f:
        analysis_response = f.read()
    print(">>> AST analysis_response extracted.\n\n.")
    
    ### testing ###
    # analysis_pure_text = atg.analyze_pure_test(pure_text)
    # print(">>> Pure text analysis_response extracted.\n\n.")
    
    with open(f"./expected_microservice_endpoint/{TARGET_ZIP_FILE}_expected_microservice_endpoints.yaml", "r", encoding="utf-8") as f:
        expected_endpoint = yaml.safe_load(f)
    
    atg.generate_api_test(analysis_response, prompt_test_cases, expected_endpoint)
    
    
    # atg.generate_api_test(analysis_pure_text, prompt_test_cases, expected_endpoint)



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


