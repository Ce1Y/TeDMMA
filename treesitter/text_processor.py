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
    if file_path.endswith("Entity.java") or file_path.endswith("Document.java") or file_path.endswith("Table.java"): return "ENTITY"
    if file_path.endswith("Repository.java") or file_path.endswith("Dao.java"): return "REPOSITORY"
    if file_path.endswith(("Dto.java", "DTO.java", "Request.java", "Response.java", "VO.java")): return "DTO"
    
    # 2. 判斷內容關鍵字 (Regex)
    patterns = {
        "TEST": r"@Test|@ParameterizedTest|@SpringBootTest",
        "CONTROLLER": r"@(Rest)?Controller",
        "SERVICE": r"@Service",
        "ENTITY": r"@Entity|@Table|@Document",
        "REPOSITORY": r"@Repository|extends\s+(JpaRepository|CrudRepository)|\bRepository\b",
        "DTO": r"@Data|@Value|@Builder|@JsonProperty|(?<!class\s)\brecord\b|implements\s+Serializable"
    }
    
    class_match = re.search(r"\b(class|record)\s+(\w+)", content)
    class_name = class_match.group(2) if class_match else ""

    def has_annotation(pattern):
        return re.search(pattern, content)
        
    # 判斷順序很重要（由明確到模糊）
    if has_annotation(r"@Test|@ParameterizedTest|@SpringBootTest"):
        return "TEST"

    if has_annotation(r"@(Rest)?Controller") or re.search(r"class\s+\w*Controller\b", content):
        return "CONTROLLER"

    if has_annotation(r"@Service") or class_name.endswith("Service"):
        return "SERVICE"

    if has_annotation(r"@Repository") or re.search(r"class\s+\w*Repository\b", content) or \
    re.search(r"extends\s+(JpaRepository|CrudRepository)", content):
        return "REPOSITORY"

    if has_annotation(r"@Entity|@Table|@Document"):
        return "ENTITY"

    if has_annotation(r"@Data|@Value|@Builder|@JsonProperty") or \
        class_name.endswith("DTO") or \
        class_name.endswith("Dto") or \
        re.search(r"\brecord\b", content) or \
        re.search(r"implements\s+Serializable", content):
        return "DTO"
    
    # for label, pattern in patterns.items():
    #     if re.search(pattern, content):
    #         return label

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
        # print(code_content)
        
        class_type = fast_regex_classify(file_path, code_content)
            
        processed_results.append([class_type, code_content])
    
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
    # entity_info = {
    #     "entity_name": None,
    #     "component_type": "Entity",
    #     "fields": [],
    #     "annotations": [] # 若有 class-level 標記可在此擴充
    # }

    # def get_text(node):
    #     if node is None: return None
    #     return source_code[node.start_byte:node.end_byte].decode('utf-8')

    # entity_name_set = False

    # for pattern_id, capture in matches:
    #     entity_node = capture.get('entity.name', [None])[0]
    #     if not entity_node:
    #         continue

    #     entity_name = get_text(entity_node)

    #     if not entity_name_set:
    #         entity_info["entity_name"] = entity_name
    #         entity_name_set = True

    #     field_name_node = capture.get('field.name', [None])[0]
    #     field_type_node = capture.get('field.type', [None])[0]
    #     field_anno_node = capture.get('field.annotation', [None])[0]

    #     if field_name_node:
    #         field_data = {
    #             "name": get_text(field_name_node),
    #             "type": get_text(field_type_node),
    #             "annotation": f"@{get_text(field_anno_node)}" if field_anno_node else None
    #         }
    #         entity_info["fields"].append(field_data)

    # === test post-processing ===
    entity_info = {
        "entity_name": None,
        "component_type": "Entity",
        "superclass": None,      # 新增：儲存父類別
        "annotations": [],       # 新增：儲存類別層級註解
        "fields": []
    }

    def get_text(node):
        if node is None: return None
        return source_code[node.start_byte:node.end_byte].decode('utf-8')

    # 用於對欄位進行去重與聚合的字典，Key 使用欄位節點的唯一範圍 (start_byte, end_byte)
    fields_dict = {}
    class_annotations_set = set()

    for pattern_id, capture in matches:
        # 1. 處理類別名稱與父類別（僅需處理一次）
        if not entity_info["entity_name"]:
            entity_node = capture.get('entity.name', [None])[0]
            if entity_node:
                entity_info["entity_name"] = get_text(entity_node)
            
            superclass_node = capture.get('entity.superclass', [None])[0]
            if superclass_node:
                entity_info["superclass"] = get_text(superclass_node)

        # 2. 收集類別層級註解 (將陣列中所有的註解都拿出來並去重)
        entity_anno_nodes = capture.get('entity.annotation', [])
        for anno_node in entity_anno_nodes:
            anno_text = get_text(anno_node)
            if anno_text:
                class_annotations_set.add(f"@{anno_text}")

        # 3. 處理欄位層級資訊
        field_node = capture.get('entity.field', [None])[0]
        if field_node:
            field_key = (field_node.start_byte, field_node.end_byte) # 欄位的唯一識別元
            
            # 如果這個欄位還沒被建立過，先初始化
            if field_key not in fields_dict:
                field_name_node = capture.get('field.name', [None])[0]
                field_type_node = capture.get('field.type', [None])[0]
                
                fields_dict[field_key] = {
                    "name": get_text(field_name_node),
                    "type": get_text(field_type_node),
                    "annotations": [] # 改為陣列，容納多個註解
                }
            
            # 聚合該欄位在這次 match 中包含的所有註解
            field_anno_nodes = capture.get('field.annotation', [])
            for anno_node in field_anno_nodes:
                anno_text = get_text(anno_node)
                if anno_text and f"@{anno_text}" not in fields_dict[field_key]["annotations"]:
                    fields_dict[field_key]["annotations"].append(f"@{anno_text}")

    # 4. 將收集好的集合與字典轉回最終的 output 格式
    entity_info["annotations"] = list(class_annotations_set)
    entity_info["fields"] = list(fields_dict.values())

    return entity_info

def process_dto_features(matches: List[tuple], source_code: bytes):
    def get_text(node):
        return source_code[node.start_byte:node.end_byte].decode('utf8')

    dto_info = {
            "dto_name": None,
            "superclass": None,
            "annotations": set(),
            "fields": {}
        }

    for match_id, captures in matches:
        if 'dto.name' in captures:
            dto_info["dto_name"] = get_text(captures['dto.name'][0])

        if 'dto.parent' in captures:
            dto_info["superclass"] = get_text(captures['dto.parent'][0])

        if 'class.annotation' in captures:
            for node in captures['class.annotation']:
                dto_info["annotations"].add(get_text(node))

        if 'field.entry' in captures:
            field_node = captures['field.entry'][0]
            field_id = field_node.start_byte

            if field_id not in dto_info["fields"]:
                dto_info["fields"][field_id] = {
                    "name": None,
                    "type": None,
                    "annotations": set(),
                    "default_value": None
                }

            if 'field.name' in captures:
                dto_info["fields"][field_id]["name"] = get_text(captures['field.name'][0])

            if 'field.type' in captures:
                dto_info["fields"][field_id]["type"] = get_text(captures['field.type'][0])

            if 'field.annotation' in captures:
                for node in captures['field.annotation']:
                    dto_info["fields"][field_id]["annotations"].add(get_text(node))

            if 'field.default_value' in captures:
                dto_info["fields"][field_id]["default_value"] = get_text(captures['field.default_value'][0])

    # 轉換 fields：移除 start_byte key
    dto_info["fields"] = list(dto_info["fields"].values())

    # set 轉 list（避免不可序列化）
    dto_info["annotations"] = list(dto_info["annotations"])
    for f in dto_info["fields"]:
        f["annotations"] = list(f["annotations"])

    return dto_info
    

def process_repository_features(matches, source_code):
    def get_text(node):
        return source_code[node.start_byte:node.end_byte].decode('utf8')

    repo_data = {
        'repo_name': None,
        'component_type': 'Repository',
        'base_interface': None,
        'managed_entity': None,
        'id_type': None,
        'methods': [],
        'annotations': [], # 視 Query 內容可擴充
        'docstring': None
    }

    for _, captures in matches:
        # 1. 處理 Repository 基本定義
        if 'repo.name' in captures:
            repo_data['repo_name'] = get_text(captures['repo.name'][0])
            repo_data['base_interface'] = get_text(captures.get('repo.base_interface', [None])[0])
            repo_data['managed_entity'] = get_text(captures.get('repo.managed_entity', [None])[0])
            repo_data['id_type'] = get_text(captures.get('repo.id_type', [None])[0])

        # 2. 處理 Repository 內定義的方法 (Query Methods)
        if 'repo.method' in captures:
            method_info = {
                'name': get_text(captures.get('method.name', [None])[0]),
                'return_type': get_text(captures.get('method.return_type', [None])[0]),
                'params': get_text(captures.get('method.params', [None])[0]),
                'annotations': [] # 如果 Query 有擷取 @Query 標註可放這
            }
            # 濾除空值並加入列表
            if method_info['name']:
                repo_data['methods'].append(method_info)

    return repo_data