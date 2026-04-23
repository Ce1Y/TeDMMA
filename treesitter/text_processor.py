import re
import zipfile
import os
import json
from langchain_community.document_loaders.generic import GenericLoader
from langchain_community.document_loaders.parsers import LanguageParser
from langchain_text_splitters import Language
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field

class MethodSignature(BaseModel):
    name: str
    method_path: Optional[str] = None  # 新增此欄位來儲存 path
    params: List[str]
    return_type: str

class ClassFeature(BaseModel):
    class_name: str
    component_type: str  # Controller, Service, Repository...
    class_path: str
    annotations: List[str]  # @RestController, @Service...
    dependencies: List[str] 
    methods: List[MethodSignature]
    docstring: Optional[str] = None

class EntityField(BaseModel):
    name: str
    field_type: str
    annotations: List[str] = []
    is_primary_key: bool = False

class EntityFeature(BaseModel):
    class_name: str
    class_annotations: List[str] = []
    fields: List[EntityField] = []

class RepoMethod(BaseModel):
    name: str
    return_type: str

class RepositoryFeature(BaseModel):
    repo_name: str
    managed_entity: str  # 關鍵：管理的實體類別
    id_type: str         # 主鍵型別
    methods: List[RepoMethod] = []


def fast_regex_classify(file_path: str, content: str):
    if "/test/" in file_path.lower() or file_path.endswith("Test.java") or file_path.endswith("Tests.java"):
        return "TEST"
    
    if file_path.endswith("Controller.java"): return "CONTROLLER"
    if file_path.endswith("Service.java") or file_path.endswith("ServiceImpl.java"): return "SERVICE"
    if file_path.endswith("Repository.java") or file_path.endswith("Dao.java"): return "REPOSITORY"

    # 2. 判斷內容關鍵字 (Regex)
    patterns = {
        "TEST": r"@Test|@ParameterizedTest|@SpringBootTest",
        "CONTROLLER": r"@(Rest)?Controller",
        "SERVICE": r"@Service",
        "ENTITY": r"@Entity|@Table|@Document",
        "REPOSITORY": r"@Repository|extends\s+(JpaRepository|CrudRepository)|\binterface\b"
    }

    for label, pattern in patterns.items():
        if re.search(pattern, content):
            return label

    return "UNKNOWN"


def load_java_project(zip_path: str, extract_path: str = "./temp_project_source"):
    zip_name = os.path.splitext(os.path.basename(zip_path))[0]
    target_dir = os.path.join(extract_path, zip_name)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(target_dir)
    
    loader = GenericLoader.from_filesystem(
        target_dir,
        glob="**/*.java",
        suffixes=[".java"],
        parser=LanguageParser(language=Language.JAVA, parser_threshold=500)
    )
    
    docs = loader.load()
    
    processed_results = []
    for doc in docs:
        file_path = doc.metadata.get("source", "")
        code_content = doc.page_content
        # print(file_path)
        # print("=========================")
        # print(code_content)
        
        final_type = fast_regex_classify(file_path, code_content)
            
        processed_results.append([final_type, code_content])
    
    return processed_results


def process_java_captures(matches: List[tuple], source_code: bytes) -> ClassFeature:
    def get_text(node):
        return source_code[node.start_byte:node.end_byte].decode('utf8')
    
    class_data = {
        "annotations": [],
        "dependencies": [],
        "methods": [],
        "class_name": "",
        "component_type": "Unknown"
    }

    for match_id, captures in matches:
        if 'class.name' in captures:
            class_data["class_name"] = get_text(captures['class.name'][0])
        
        if 'class.annotation' in captures:
            for anno_node in captures['class.annotation']:
                anno_text = anno_text = f"@{get_text(anno_node)}"
                class_data["annotations"].append(anno_text)

                if "Controller" in anno_text: class_data["component_type"] = "Controller"
                elif "Service" in anno_text: class_data["component_type"] = "Service"
                elif "Repository" in anno_text: class_data["component_type"] = "Repository"

        if 'dep.type' in captures:
            class_data["dependencies"].append(get_text(captures['dep.type'][0]))

        if 'method.name' in captures:
            ret_type = get_text(captures['method.return_type'][0]) if 'method.return_type' in captures else "void"
            method_name = get_text(captures['method.name'][0])
            
            params = []
            if 'method.param_type' in captures and 'method.param_name' in captures:
                types = [get_text(n) for n in captures['method.param_type']]
                names = [get_text(n) for n in captures['method.param_name']]
                params = [f"{t} {n}" for t, n in zip(types, names)]

            class_data["methods"].append(
                # MethodSignature(name=method_name, params=params, return_type=ret_type)
                {
                    "name": method_name,
                    "method_path": None,
                    "params": params,
                    "return_type": ret_type
                }
            )

    return ClassFeature(
        class_path="None",
        **class_data
    )


def process_path_features(matches, source_code):
    paths = {
        "class_path": None,
        "methods_path": {} # key: method_name, value: path
    }
    
    def get_text(node):
        return source_code[node.start_byte:node.end_byte].decode('utf8')

    for match_id, captures in matches:
        if 'path.class' in captures:
            paths["class_path"] = get_text(captures['path.class'][0])
            
        if 'path.method' in captures and 'method.name' in captures:
            m_name = get_text(captures['method.name'][0])
            m_path = get_text(captures['path.method'][0])
            paths["methods_path"][m_name] = m_path
            
    return paths


def process_entity_features(matches: List[tuple], source_code: bytes) -> EntityFeature:
    """
    matches: tree-sitter query.matches() 的輸出
    source_code: 原始碼的 bytes 或 string
    """
    entities = {}

    for pattern_index, captures in matches:
        entity_node = captures.get('entity.name')[0]
        entity_name = source_code[entity_node.start_byte : entity_node.end_byte].decode('utf-8')
        
        if entity_name not in entities:
            entities[entity_name] = {"fields": {}, "enums": {}}

        if 'field.name' in captures:
            f_name_node = captures['field.name'][0]
            f_name = source_code[f_name_node.start_byte : f_name_node.end_byte].decode('utf-8')
            
            if f_name not in entities[entity_name]["fields"]:
                f_type_node = captures['field.type'][0]
                entities[entity_name]["fields"][f_name] = {
                    "type": source_code[f_type_node.start_byte : f_type_node.end_byte].decode('utf-8'),
                    "annotations": set()
                }
            
            if 'field.annotation' in captures:
                for anno_node in captures['field.annotation']:
                    anno_text = source_code[anno_node.start_byte : anno_node.end_byte].decode('utf-8')
                    entities[entity_name]["fields"][f_name]["annotations"].add(anno_text)

        if 'enum.name' in captures:
            e_name_node = captures['enum.name'][0]
            e_name = source_code[e_name_node.start_byte : e_name_node.end_byte].decode('utf-8')
            
            if e_name not in entities[entity_name]["enums"]:
                entities[entity_name]["enums"][e_name] = []
            
            if 'enum.member' in captures:
                for m_node in captures['enum.member']:
                    m_text = source_code[m_node.start_byte : m_node.end_byte].decode('utf-8')
                    entities[entity_name]["enums"][e_name].append(m_text)

    output = []
    for e_name, content in entities.items():
        entity_data = {
            "entity": e_name,
            "fields": [
                {
                    "name": fname,
                    "type": fval["type"],
                    "annotations": list(fval["annotations"])
                } for fname, fval in content["fields"].items()
            ],
            "enums": [
                { "name": ename, "members": members } for ename, members in content["enums"].items()
            ]
        }
        output.append(entity_data)
    
    # return json.dumps(output, indent=2, ensure_ascii=False)
    return output


def process_repository_features(matches, source_code):
    def get_text(node):
        return source_code[node.start_byte:node.end_byte].decode('utf8')

    repo_data = {
        "repo_name": "",
        "managed_entity": "",
        "id_type": "",
        "methods": []
    }

    for _, captures in matches:
        if 'repo.name' in captures:
            repo_data["repo_name"] = get_text(captures['repo.name'][0])
        
        if 'repo.managed_entity' in captures:
            repo_data["managed_entity"] = get_text(captures['repo.managed_entity'][0])
            
        if 'repo.id_type' in captures:
            repo_data["id_type"] = get_text(captures['repo.id_type'][0])

        if 'method.name' in captures:
            m_name = get_text(captures['method.name'][0])
            m_ret = get_text(captures['method.return_type'][0]) if 'method.return_type' in captures else "void"
            
            # 避免重複添加 (Tree-sitter match 特性)
            if not any(m.name == m_name for m in repo_data["methods"]):
                repo_data["methods"].append(RepoMethod(name=m_name, return_type=m_ret))

    return RepositoryFeature(**repo_data)