from dataclasses import dataclass, field
from pathlib import Path


MODEL_TAGS = {"MMDL", "MODL"}
MESH_TAGS = {"MESH"}
KEY_TAGS = {"KEYF"}
MAT_TAGS = {"MAT"}
CMP_TAGS = {"cmap"}


@dataclass
class CosComponent:
    id: int
    tagId: int
    tag: str
    hash: int
    parentId: int
    name: str
    assetName: str
    extension: str
    children: list = field(default_factory = list)


@dataclass
class CosModel:
    component: CosComponent
    parentModelId: int = None
    children: list = field(default_factory = list)
    models: list = field(default_factory = list)
    materials: list = field(default_factory = list)
    colormaps: list = field(default_factory = list)
    keys: list = field(default_factory = list)
    otherAssets: list = field(default_factory = list)

    @property
    def id(self):
        return self.component.id

    @property
    def name(self):
        return self.component.assetName


def ParseCos(pathOrData):
    text = ReadCosText(pathOrData)
    components = ParseCosComponentsFromText(text)
    hierarchy = BuildCosHierarchy(components)

    return {
        "components": components,
        "componentsById": {
            component.id: component
            for component in components
        },
        "rootModels": hierarchy["rootModels"],
        "models": hierarchy["models"],
        "modelsById": hierarchy["modelsById"],
    }


def ReadCosText(pathOrData):
    if isinstance(pathOrData, bytes):
        return pathOrData.decode("latin-1", errors = "replace")

    if isinstance(pathOrData, bytearray):
        return bytes(pathOrData).decode("latin-1", errors = "replace")

    path = Path(pathOrData)

    return path.read_text(encoding = "latin-1", errors = "replace")


def ParseCosComponentsFromText(text):
    tagNames = {}
    components = []
    inTags = False
    inComponents = False

    for rawLine in text.splitlines():
        line = rawLine.strip()

        if line == "" or line.startswith("#"):
            continue

        lowerLine = line.lower()

        if lowerLine == "section tags":
            inTags = True
            inComponents = False
            continue

        if lowerLine == "section components":
            inTags = False
            inComponents = True
            continue

        if lowerLine.startswith("section "):
            inTags = False
            inComponents = False
            continue

        if inTags:
            tag = ParseTagLine(line)

            if tag is not None:
                tagId, tagName = tag
                tagNames[tagId] = tagName

        elif inComponents:
            component = ParseComponentLine(line, tagNames)

            if component is not None:
                components.append(component)

    return components


def ParseTagLine(line):
    parts = line.split()

    if len(parts) < 2 or not IsInteger(parts[0]):
        return None

    tagId = int(parts[0])
    tagName = parts[1].strip("'\"")

    return tagId, tagName


def ParseComponentLine(line, tagNames):
    parts = line.split(None, 4)

    if len(parts) < 5 or not IsInteger(parts[0]):
        return None

    componentId = int(parts[0])
    tagId = int(parts[1])
    hashValue = int(parts[2])
    parentId = int(parts[3])
    name = parts[4].strip()
    assetName = GetAssetName(name)

    return CosComponent(
        id = componentId,
        tagId = tagId,
        tag = tagNames.get(tagId, ""),
        hash = hashValue,
        parentId = parentId,
        name = name,
        assetName = assetName,
        extension = Path(assetName).suffix.lower(),
    )


def BuildCosHierarchy(components):
    componentsById = {
        component.id: component
        for component in components
    }

    for component in components:
        parent = componentsById.get(component.parentId)

        if parent is not None:
            parent.children.append(component)

    modelComponents = [
        component
        for component in components
        if IsModelComponent(component)
    ]
    modelsById = {
        component.id: CosModel(component = component)
        for component in modelComponents
    }

    for model in modelsById.values():
        model.parentModelId = FindNearestParentModelId(
            model.component.parentId,
            componentsById,
            modelsById,
        )

    for model in modelsById.values():
        if model.parentModelId in modelsById:
            parentModel = modelsById[model.parentModelId]
            parentModel.models.append(model)
            parentModel.children.append(model)

    for component in components:
        if IsModelComponent(component) or IsMeshComponent(component):
            continue

        modelId = FindNearestParentModelId(
            component.parentId,
            componentsById,
            modelsById,
        )

        if modelId not in modelsById:
            continue

        AddComponentToModel(modelsById[modelId], component)

    rootModels = [
        model
        for model in modelsById.values()
        if model.parentModelId not in modelsById
    ]

    rootModels.sort(key = lambda model: model.id)

    return {
        "rootModels": rootModels,
        "models": sorted(modelsById.values(), key = lambda model: model.id),
        "modelsById": modelsById,
    }


def AddComponentToModel(model, component):
    if IsKeyComponent(component):
        model.keys.append(component)
    elif IsMatComponent(component):
        model.materials.append(component)
    elif IsCmpComponent(component):
        model.colormaps.append(component)
    else:
        model.otherAssets.append(component)

    model.children.append(component)


def FindNearestParentModelId(parentId, componentsById, modelsById):
    visited = set()
    currentId = parentId

    while currentId >= 0 and currentId not in visited:
        visited.add(currentId)

        if currentId in modelsById:
            return currentId

        component = componentsById.get(currentId)

        if component is None:
            return None

        currentId = component.parentId

    return None


def IsModelComponent(component):
    return component.tag in MODEL_TAGS or component.extension == ".3do"


def IsMeshComponent(component):
    return component.tag in MESH_TAGS or component.name.lower().startswith("mesh ")


def IsKeyComponent(component):
    return component.tag in KEY_TAGS or component.extension == ".key"


def IsMatComponent(component):
    normalizedTag = component.tag.strip()
    return normalizedTag in MAT_TAGS or component.extension == ".mat"


def IsCmpComponent(component):
    return component.tag in CMP_TAGS or component.extension == ".cmp"


def GetAssetName(name):
    return name.split(",", 1)[0].strip()


def IsInteger(value):
    try:
        int(value)
        return True
    except ValueError:
        return False


def ModelToDict(model):
    return {
        "id": model.id,
        "name": model.name,
        "component": ComponentToDict(model.component),
        "parentModelId": model.parentModelId,
        "models": [
            ModelToDict(childModel)
            for childModel in model.models
        ],
        "materials": [
            ComponentToDict(component)
            for component in model.materials
        ],
        "colormaps": [
            ComponentToDict(component)
            for component in model.colormaps
        ],
        "keys": [
            ComponentToDict(component)
            for component in model.keys
        ],
        "otherAssets": [
            ComponentToDict(component)
            for component in model.otherAssets
        ],
    }


def ComponentToDict(component):
    return {
        "id": component.id,
        "tagId": component.tagId,
        "tag": component.tag,
        "hash": component.hash,
        "parentId": component.parentId,
        "name": component.name,
        "assetName": component.assetName,
        "extension": component.extension,
    }
