bl_info = {
    "name": "GF Model Tools",
    "author": "Dieter \"squink\" Stassen",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > GF Tools",
    "description": "Tools for working with Grim Fandango models and animations.",
    "category": "Import-Export",
}

import importlib
import bpy
from pathlib import Path
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .core import export3do_with_materials
from .core import import_key_animation
from .core import import_skeleton
from .core import lab_archive
from .core import cos_parser

export3do_with_materials = importlib.reload(export3do_with_materials)
import_key_animation = importlib.reload(import_key_animation)
import_skeleton = importlib.reload(import_skeleton)
lab_archive = importlib.reload(lab_archive)
cos_parser = importlib.reload(cos_parser)

CleanMaterialName = export3do_with_materials.CleanMaterialName
ConvertUv = export3do_with_materials.ConvertUv
GetMatInfo = export3do_with_materials.GetMatInfo
Parse3DO = export3do_with_materials.Parse3DO
ReadPalette = export3do_with_materials.ReadPalette
ResolveCmpFromCos = export3do_with_materials.ResolveCmpFromCos
TransformPoint = export3do_with_materials.TransformPoint
ImportKeyAnimation = import_key_animation.ImportKeyAnimation
ImportSkeleton = import_skeleton.ImportSkeleton
ModelToSkeleton = import_skeleton.ModelToSkeleton
LabArchive = lab_archive.LabArchive
ParseCos = cos_parser.ParseCos

labArchiveCache = {}
cosParseCache = {}


def GetAddonSettings(context):
    return context.scene.gfModelToolsSettings


def GetLabCacheKey(path):
    path = Path(path)
    stat = path.stat()

    return (
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
    )


def GetCachedLabArchive(path):
    cacheKey = GetLabCacheKey(path)
    archive = labArchiveCache.get(cacheKey)

    if archive is None:
        archive = LabArchive(path)
        archive.cacheKey = cacheKey

        if len(labArchiveCache) > 24:
            labArchiveCache.clear()
            cosParseCache.clear()

        labArchiveCache[cacheKey] = archive

    return archive


def GetCachedParsedCos(archive, cosName):
    cacheKey = (archive.cacheKey, cosName)
    parsedCos = cosParseCache.get(cacheKey)

    if parsedCos is None:
        parsedCos = ParseCos(archive.ReadEntry(cosName))

        if len(cosParseCache) > 32:
            cosParseCache.clear()

        cosParseCache[cacheKey] = parsedCos

    return parsedCos


def GetRelatedLabPaths(primaryLabPath):
    primaryLabPath = Path(primaryLabPath)
    labFolder = primaryLabPath.parent
    labPaths = [
        path
        for path in labFolder.glob("*.LAB")
    ]
    labPaths.extend(
        path
        for path in labFolder.glob("*.lab")
        if path not in labPaths
    )

    primaryResolved = primaryLabPath.resolve()

    def SortKey(path):
        name = path.name.lower()

        if path.resolve() == primaryResolved:
            return (0, 0, name)

        if name == "data000.lab":
            return (1, 0, name)

        dataIndex = GetDataLabIndex(name)

        if dataIndex is not None:
            return (2, dataIndex, name)

        return (3, 0, name)


    return sorted(labPaths, key = SortKey)


def GetDataLabIndex(name):
    if not name.startswith("data") or not name.endswith(".lab"):
        return None

    indexText = name[4:-4]

    if len(indexText) == 0 or not indexText.isdigit():
        return None

    return int(indexText)


def FindLabEntryInRelatedLabs(primaryArchive, name):
    entry = primaryArchive.Find(name)

    if entry is not None:
        return primaryArchive, entry

    for labPath in GetRelatedLabPaths(primaryArchive.path):
        if labPath.resolve() == primaryArchive.path.resolve():
            continue

        try:
            archive = GetCachedLabArchive(labPath)
        except Exception:
            continue

        entry = archive.Find(name)

        if entry is not None:
            return archive, entry

    return None, None


def FindLabEntryWithMagicInRelatedLabs(primaryArchive, name, magic):
    checkedEntries = []

    for archive in GetRelatedLabArchives(primaryArchive):
        entry = archive.Find(name)

        if entry is None:
            continue

        checkedEntries.append(f"{archive.path.name}:{entry.name}")

        if archive.ReadEntryPrefix(entry, len(magic)) == magic:
            data = archive.ReadEntry(entry)
            return archive, entry, data

    return None, None, None


def FindKeyEntryInRelatedLabs(primaryArchive, name):
    for archive in GetRelatedLabArchives(primaryArchive):
        entry = archive.Find(name)

        if entry is None:
            continue

        prefix = archive.ReadEntryPrefix(entry, 512)

        if IsSupportedKeyPrefix(prefix):
            return archive, entry, archive.ReadEntry(entry)

    return None, None, None


def IsSupportedKeyPrefix(prefix):
    if prefix.startswith(b"FYEK"):
        return True

    lowerPrefix = prefix.lower()

    return (
        b"keyframe" in lowerPrefix and
        b"section: header" in lowerPrefix
    )


def GetRelatedLabArchives(primaryArchive):
    yield primaryArchive

    for labPath in GetRelatedLabPaths(primaryArchive.path):
        if labPath.resolve() == primaryArchive.path.resolve():
            continue

        try:
            yield GetCachedLabArchive(labPath)
        except Exception:
            continue


def FindLabEntryOptionsInRelatedLabs(primaryArchive, names):
    for name in names:
        archive, entry = FindLabEntryInRelatedLabs(primaryArchive, name)

        if entry is not None:
            return archive, entry

    return None, None


def GetLabArchiveFromSettings(settings):
    if settings.labPath == "":
        return None

    return GetCachedLabArchive(settings.labPath)


def GetCosItems(self, context):
    if self.labPath == "":
        return [("__NONE__", "Select a COS file", "")]

    try:
        archive = GetCachedLabArchive(self.labPath)
        cosEntries = archive.Filter(".cos")
    except Exception:
        return [("__NONE__", "Could not read LAB", "")]

    if len(cosEntries) == 0:
        return [("__NONE__", "No COS files found", "")]

    return [
        (entry.name, entry.name, "")
        for entry in cosEntries
    ]


def GetThreeDoItems(self, context):
    if self.labPath == "" or self.cosName == "__NONE__":
        return [("__NONE__", "Select a 3DO file", "")]

    try:
        archive = GetCachedLabArchive(self.labPath)
        parsedCos = GetCachedParsedCos(archive, self.cosName)
    except Exception:
        return [("__NONE__", "Could not parse COS", "")]

    models = parsedCos["models"]

    if len(models) == 0:
        return [("__NONE__", "No 3DO files found", "")]

    items = []

    for model in models:
        label = model.name

        if model.id == 0:
            label = f"{label} (main)"

        items.append((str(model.id), label, ""))

    return items


def GetKeyItems(self, context):
    if (
        self.labPath == "" or
        self.cosName == "__NONE__" or
        self.threeDoComponentId == "__NONE__"
    ):
        return [("__NONE__", "Select a KEY file", "")]

    try:
        _archive, _parsedCos, cosModel = GetSelectedCosModel(self)
    except Exception:
        return [("__NONE__", "Could not read KEY list", "")]

    keyItems = []

    for key in cosModel.keys:
        _keyArchive, keyEntry, _keyData = FindKeyEntryInRelatedLabs(_archive, key.assetName)

        if keyEntry is not None:
            keyItems.append((str(key.id), key.assetName, ""))

    if len(keyItems) == 0:
        return [("__NONE__", "No KEY files found", "")]

    return keyItems


def SelectFirstEnumItem(settings, propertyName, items):
    if len(items) == 0 or items[0][0] == "__NONE__":
        try:
            setattr(settings, propertyName, "__NONE__")
        except TypeError:
            pass

        return

    try:
        setattr(settings, propertyName, items[0][0])
    except TypeError:
        pass


def OnCosChanged(self, context):
    threeDoItems = GetThreeDoItems(self, context)
    SelectFirstEnumItem(self, "threeDoComponentId", threeDoItems)
    keyItems = GetKeyItems(self, context)
    SelectFirstEnumItem(self, "keyComponentId", keyItems)


def OnThreeDoChanged(self, context):
    keyItems = GetKeyItems(self, context)
    SelectFirstEnumItem(self, "keyComponentId", keyItems)


def GetSelectedCos(settings):
    archive = GetLabArchiveFromSettings(settings)

    if archive is None:
        raise ValueError("Select a LAB file first")

    if settings.cosName == "__NONE__":
        raise ValueError("Select a COS file first")

    parsedCos = GetCachedParsedCos(archive, settings.cosName)

    return archive, parsedCos


def GetSelectedCosModel(settings):
    if settings.threeDoComponentId == "__NONE__":
        raise ValueError("Select a 3DO file first")

    archive, parsedCos = GetSelectedCos(settings)
    modelId = int(settings.threeDoComponentId)
    cosModel = parsedCos["modelsById"].get(modelId)

    if cosModel is None:
        raise ValueError("Selected 3DO file is not listed in the selected COS")

    return archive, parsedCos, cosModel


def GetSelectedKeyComponent(settings):
    if settings.keyComponentId == "__NONE__":
        raise ValueError("Select a KEY file first")

    _archive, _parsedCos, cosModel = GetSelectedCosModel(settings)
    keyId = int(settings.keyComponentId)

    for keyComponent in cosModel.keys:
        if keyComponent.id == keyId:
            return keyComponent

    raise ValueError("Selected KEY file is not attached to the selected 3DO")


def IsImportReady(settings):
    try:
        GetSelectedCosModel(settings)
        return True
    except Exception:
        return False


def IsAnimationReady(settings):
    try:
        archive, _parsedCos, _cosModel = GetSelectedCosModel(settings)
        keyComponent = GetSelectedKeyComponent(settings)
        _keyArchive, keyEntry, _keyData = FindKeyEntryInRelatedLabs(archive, keyComponent.assetName)
        return keyEntry is not None
    except Exception:
        return False


def FindMatPath(material, matFolder):
    matFolder = Path(matFolder)
    materialName = CleanMaterialName(material)
    matPath = matFolder / material

    if matPath.exists():
        return matPath

    matPath = matFolder / f"{materialName}.mat"

    if matPath.exists():
        return matPath

    return matFolder / material


def CreateImageFromMat(matPath, imageInfo, palette, materialName):
    data = Path(matPath).read_bytes()
    imageNameBase = Path(matPath).stem

    return CreateImageFromMatData(data, imageInfo, palette, materialName, imageNameBase)


def CreateImageFromMatData(data, imageInfo, palette, materialName, imageNameBase):
    width = imageInfo["width"]
    height = imageInfo["height"]
    hasAlpha = imageInfo["hasAlpha"]
    dataOffset = imageInfo["dataOffset"]
    pixelCount = imageInfo["pixelCount"]
    indices = data[dataOffset:dataOffset + pixelCount]
    pixels = []

    for blenderY in range(height):
        sourceY = height - 1 - blenderY

        for x in range(width):
            index = indices[(sourceY * width) + x]
            r, g, b, a = palette[index]

            if hasAlpha != 0 and index == 0:
                a = 0

            pixels.extend((
                r / 255.0,
                g / 255.0,
                b / 255.0,
                a / 255.0,
            ))

    imageName = f"{materialName}_{imageNameBase}"

    if imageName in bpy.data.images:
        image = bpy.data.images[imageName]

        if image.size[0] != width or image.size[1] != height:
            bpy.data.images.remove(image)
            image = bpy.data.images.new(imageName, width = width, height = height, alpha = True)
    else:
        image = bpy.data.images.new(imageName, width = width, height = height, alpha = True)

    image.pixels.foreach_set(pixels)
    image.update()
    image.pack()
    return image


def GetOrCreateMaterial(name, image = None, usesAlpha = False):
    materialName = CleanMaterialName(name)

    if materialName in bpy.data.materials:
        material = bpy.data.materials[materialName]
    else:
        material = bpy.data.materials.new(materialName)
        material.diffuse_color = (1.0, 1.0, 1.0, 1.0)

    if image is not None:
        material.use_nodes = True
        material.blend_method = "CLIP" if usesAlpha else "OPAQUE"
        material.use_backface_culling = False

        if usesAlpha:
            material.alpha_threshold = 0.5

        nodes = material.node_tree.nodes
        links = material.node_tree.links
        principled = nodes.get("Principled BSDF")

        if principled is not None:
            imageNode = nodes.new(type = "ShaderNodeTexImage")
            imageNode.image = image
            links.new(imageNode.outputs["Color"], principled.inputs["Base Color"])

            if usesAlpha and "Alpha" in principled.inputs:
                links.new(imageNode.outputs["Alpha"], principled.inputs["Alpha"])

    return material


def BuildBlenderMaterialInfo(materials, matFolder, cmpPath):
    palette = ReadPalette(cmpPath)
    materialInfo = []

    for material in materials:
        materialName = CleanMaterialName(material)
        matPath = FindMatPath(material, matFolder)

        info = {
            "name": materialName,
            "matPath": matPath,
            "width": 64,
            "height": 64,
            "image": None,
            "usesAlpha": False,
            "found": False,
        }

        if matPath.exists():
            matInfo = GetMatInfo(matPath)
            firstImage = matInfo["images"][0]

            info["width"] = firstImage["width"]
            info["height"] = firstImage["height"]
            info["usesAlpha"] = firstImage["hasAlpha"] != 0
            info["image"] = CreateImageFromMat(
                matPath,
                firstImage,
                palette,
                materialName,
            )
            info["found"] = True

        materialInfo.append(info)

    return materialInfo


def FindLabEntryByNameOptions(archive, names):
    _archive, entry = FindLabEntryOptionsInRelatedLabs(archive, names)
    return entry


def GetCosModelColormap(cosModel, parsedCos):
    currentModel = cosModel

    while currentModel is not None:
        if len(currentModel.colormaps) > 0:
            return currentModel.colormaps[0]

        currentModel = parsedCos["modelsById"].get(currentModel.parentModelId)

    return None


def BuildBlenderMaterialInfoFromLab(materials, archive, parsedCos, cosModel):
    cmpComponent = GetCosModelColormap(cosModel, parsedCos)

    if cmpComponent is None:
        return BuildFallbackMaterialInfo(materials)

    cmpArchive, cmpEntry = FindLabEntryInRelatedLabs(archive, cmpComponent.assetName)

    if cmpEntry is None:
        return BuildFallbackMaterialInfo(materials)

    palette = ReadPalette(cmpArchive.ReadEntry(cmpEntry))
    materialInfo = []

    for material in materials:
        materialName = CleanMaterialName(material)
        matArchive, matEntry = FindLabEntryOptionsInRelatedLabs(
            archive,
            (
                material,
                f"{materialName}.mat",
            ),
        )

        info = {
            "name": materialName,
            "matPath": None,
            "width": 64,
            "height": 64,
            "image": None,
            "usesAlpha": False,
            "found": False,
        }

        if matEntry is not None:
            matData = matArchive.ReadEntry(matEntry)
            matInfo = GetMatInfo(matData)
            firstImage = matInfo["images"][0]

            info["width"] = firstImage["width"]
            info["height"] = firstImage["height"]
            info["usesAlpha"] = firstImage["hasAlpha"] != 0
            info["image"] = CreateImageFromMatData(
                matData,
                firstImage,
                palette,
                materialName,
                Path(matEntry.name).stem,
            )
            info["found"] = True

        materialInfo.append(info)

    return materialInfo


def BuildFallbackMaterialInfo(materials):
    return [
        {
            "name": CleanMaterialName(material),
            "matPath": None,
            "width": 64,
            "height": 64,
            "image": None,
            "usesAlpha": False,
            "found": False,
        }
        for material in materials
    ]


def BuildMeshObject(model, meshIndex, mesh, materialInfo, blenderMaterials, noTransform):
    points = mesh["points"]
    faces = mesh["faces"]

    if len(points) == 0:
        return None

    matrix = None

    if not noTransform:
        matrix = model["meshNodeByIndex"].get(meshIndex, {}).get("meshMatrix")

    if matrix is not None:
        vertices = [TransformPoint(matrix, point) for point in points]
    else:
        vertices = list(points)

    faceVertices = []
    sourceFaces = []

    for face in faces:
        vertexIndices = face["vertices"]

        if len(vertexIndices) < 3:
            continue

        if any(vertexIndex < 0 or vertexIndex >= len(vertices) for vertexIndex in vertexIndices):
            continue

        faceVertices.append(tuple(vertexIndices))
        sourceFaces.append(face)

    blenderMesh = bpy.data.meshes.new(mesh["name"])
    blenderMesh.from_pydata(vertices, [], faceVertices)
    blenderMesh.update()

    blenderObject = bpy.data.objects.new(mesh["name"], blenderMesh)
    blenderObject["grimMeshIndex"] = meshIndex
    blenderObject["grimSourceModel"] = model.get("modelName", "")

    materialSlots = list(blenderMaterials)
    defaultMaterial = GetOrCreateMaterial("default")
    defaultMaterialIndex = len(materialSlots)
    materialSlots.append(defaultMaterial)

    for material in materialSlots:
        blenderObject.data.materials.append(material)

    for polygonIndex, polygon in enumerate(blenderMesh.polygons):
        materialIndex = sourceFaces[polygonIndex]["material"]

        if 0 <= materialIndex < len(blenderMaterials):
            polygon.material_index = materialIndex
        else:
            polygon.material_index = defaultMaterialIndex

    if any(face["uvs"] is not None for face in sourceFaces):
        uvLayer = blenderMesh.uv_layers.new(name = "UVMap")

        for polygonIndex, polygon in enumerate(blenderMesh.polygons):
            face = sourceFaces[polygonIndex]
            uvIndices = face["uvs"]

            if uvIndices is None:
                continue

            for loopOffset, loopIndex in enumerate(polygon.loop_indices):
                if loopOffset >= len(uvIndices):
                    continue

                uvIndex = uvIndices[loopOffset]

                materialIndex = face["material"]

                if (
                    0 <= uvIndex < len(mesh["uvs"]) and
                    0 <= materialIndex < len(materialInfo)
                ):
                    u, v = mesh["uvs"][uvIndex]
                    info = materialInfo[materialIndex]
                    u, v = ConvertUv(
                        u,
                        v,
                        float(info["width"]),
                        float(info["height"]),
                        flipV = False,
                    )
                    uvLayer.data[loopIndex].uv = (u, v)

    for polygon in blenderMesh.polygons:
        polygon.use_smooth = True

    blenderMesh.update()
    return blenderObject


class GF_MODEL_TOOLS_PG_settings(bpy.types.PropertyGroup):
    showModelImporter: BoolProperty(
        name = "Model Importer",
        description = "Show model import controls",
        default = True,
    )
    showAnimationImporter: BoolProperty(
        name = "Animation Importer",
        description = "Show animation import controls",
        default = True,
    )
    labPath: StringProperty(
        name = "LAB File",
        description = "Selected Grim Fandango LAB archive",
        subtype = "FILE_PATH",
        default = "",
    )
    cosName: EnumProperty(
        name = "COS",
        description = "Costume file inside the selected LAB archive",
        items = GetCosItems,
        update = OnCosChanged,
    )
    threeDoComponentId: EnumProperty(
        name = "3DO",
        description = "3DO model listed inside the selected COS file",
        items = GetThreeDoItems,
        update = OnThreeDoChanged,
    )
    keyComponentId: EnumProperty(
        name = "KEY",
        description = "KEY animation attached to the selected 3DO model",
        items = GetKeyItems,
    )
    threeDoPath: StringProperty(
        name = "3DO File",
        description = "Selected Grim Fandango 3DO model file",
        subtype = "FILE_PATH",
        default = "",
    )
    matFolderPath: StringProperty(
        name = "MAT Folder",
        description = "Folder containing MAT texture files",
        subtype = "DIR_PATH",
        default = "",
    )
    cosPath: StringProperty(
        name = "COS File",
        description = "Costume file used to resolve the CMP palette",
        subtype = "FILE_PATH",
        default = "",
    )
    applyPose: BoolProperty(
        name = "Apply Pose",
        description = "Apply the model hierarchy pose to mesh vertices during import",
        default = False,
    )
    importSkeleton: BoolProperty(
        name = "Import Skeleton",
        description = "Create a Blender armature from the 3DO hierarchy and parent meshes to bones",
        default = False,
    )
    keyPath: StringProperty(
        name = "KEY File",
        description = "Selected Grim Fandango KEY animation file",
        subtype = "FILE_PATH",
        default = "",
    )
    animationUseSceneFps: BoolProperty(
        name = "Use Scene FPS",
        description = "Use the current Blender scene FPS as the animation target FPS",
        default = True,
    )
    animationImportMode: EnumProperty(
        name = "Mode",
        description = "Choose whether to import sparse KEY frames or sample every Blender frame",
        items = (
            ("KEYFRAMES", "Keyframes", "Only insert keyframes from the KEY file"),
            ("SAMPLED", "Sampled", "Evaluate and insert one keyframe on every Blender frame"),
        ),
        default = "KEYFRAMES",
    )


class GF_MODEL_TOOLS_OT_selectLab(bpy.types.Operator):
    bl_idname = "gf_model_tools.select_lab"
    bl_label = "Select LAB"
    bl_description = "Choose a Grim Fandango LAB archive"

    filepath: StringProperty(
        name = "LAB File",
        subtype = "FILE_PATH",
    )

    filter_glob: StringProperty(
        default = "*.lab;*.LAB",
        options = {"HIDDEN"},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = GetAddonSettings(context)
        settings.labPath = self.filepath

        try:
            cosItems = GetCosItems(settings, context)

            if cosItems[0][0] != "__NONE__":
                settings.cosName = cosItems[0][0]
                threeDoItems = GetThreeDoItems(settings, context)

                if threeDoItems[0][0] != "__NONE__":
                    settings.threeDoComponentId = threeDoItems[0][0]
                    keyItems = GetKeyItems(settings, context)

                    if keyItems[0][0] != "__NONE__":
                        settings.keyComponentId = keyItems[0][0]
        except Exception:
            pass

        return {"FINISHED"}


class GF_MODEL_TOOLS_OT_selectThreeDo(bpy.types.Operator):
    bl_idname = "gf_model_tools.select_3do"
    bl_label = "Select 3DO"
    bl_description = "Choose a Grim Fandango 3DO model file"

    filepath: StringProperty(
        name = "3DO File",
        subtype = "FILE_PATH",
    )

    filter_glob: StringProperty(
        default = "*.3do",
        options = {"HIDDEN"},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = GetAddonSettings(context)
        settings.threeDoPath = self.filepath
        return {"FINISHED"}


class GF_MODEL_TOOLS_OT_selectMatFolder(bpy.types.Operator):
    bl_idname = "gf_model_tools.select_mat_folder"
    bl_label = "Select MAT Folder"
    bl_description = "Choose the folder containing MAT texture files"

    directory: StringProperty(
        name = "MAT Folder",
        subtype = "DIR_PATH",
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = GetAddonSettings(context)
        settings.matFolderPath = self.directory
        return {"FINISHED"}


class GF_MODEL_TOOLS_OT_selectCos(bpy.types.Operator):
    bl_idname = "gf_model_tools.select_cos"
    bl_label = "Select COS"
    bl_description = "Choose the costume file used to resolve the CMP palette"

    filepath: StringProperty(
        name = "COS File",
        subtype = "FILE_PATH",
    )

    filter_glob: StringProperty(
        default = "*.cos",
        options = {"HIDDEN"},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = GetAddonSettings(context)
        settings.cosPath = self.filepath
        return {"FINISHED"}


class GF_MODEL_TOOLS_OT_selectKey(bpy.types.Operator):
    bl_idname = "gf_model_tools.select_key"
    bl_label = "Select KEY"
    bl_description = "Choose a Grim Fandango KEY animation file"

    filepath: StringProperty(
        name = "KEY File",
        subtype = "FILE_PATH",
    )

    filter_glob: StringProperty(
        default = "*.key",
        options = {"HIDDEN"},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = GetAddonSettings(context)
        settings.keyPath = self.filepath
        return {"FINISHED"}


class GF_MODEL_TOOLS_OT_extractThreeDo(bpy.types.Operator):
    bl_idname = "gf_model_tools.extract_3do"
    bl_label = "Import Model"
    bl_description = "Import the selected LAB/COS 3DO model as Blender mesh geometry"

    def execute(self, context):
        settings = GetAddonSettings(context)

        try:
            archive, parsedCos, cosModel = GetSelectedCosModel(settings)
            threeDoArchive, threeDoEntry = FindLabEntryInRelatedLabs(archive, cosModel.name)

            if threeDoEntry is None:
                raise ValueError(f"Could not find 3DO in selected LAB or sibling LABs: {cosModel.name}")

            model = Parse3DO(threeDoArchive.ReadEntry(threeDoEntry))
        except Exception as error:
            self.report({"ERROR"}, f"Could not parse 3DO: {error}")
            return {"CANCELLED"}

        try:
            materialInfo = BuildBlenderMaterialInfoFromLab(
                model["materials"],
                archive,
                parsedCos,
                cosModel,
            )
        except Exception as error:
            materialInfo = BuildFallbackMaterialInfo(model["materials"])
            self.report({"WARNING"}, f"Material import skipped: {error}")

        collection = bpy.data.collections.new(model["modelName"])
        context.scene.collection.children.link(collection)

        materials = [
            GetOrCreateMaterial(info["name"], info["image"], info["usesAlpha"])
            for info in materialInfo
        ]

        importedCount = 0
        importedObjects = []
        noTransform = (not settings.applyPose) or settings.importSkeleton

        for meshIndex, mesh in enumerate(model["meshes"]):
            blenderObject = BuildMeshObject(
                model,
                meshIndex,
                mesh,
                materialInfo,
                materials,
                noTransform,
            )

            if blenderObject is None:
                continue

            collection.objects.link(blenderObject)
            importedObjects.append(blenderObject)
            importedCount += 1

        armatureObject = None

        if settings.importSkeleton:
            armatureObject = ImportSkeleton(model, importedObjects)

        for obj in context.scene.objects:
            obj.select_set(False)

        if armatureObject is not None:
            armatureObject.select_set(True)
            context.view_layer.objects.active = armatureObject
        else:
            for obj in importedObjects:
                obj.select_set(True)

        if armatureObject is None and len(importedObjects) > 0:
            context.view_layer.objects.active = importedObjects[0]

        self.report(
            {"INFO"},
            f"Imported {importedCount} meshes from {model['modelName']}",
        )
        return {"FINISHED"}


class GF_MODEL_TOOLS_OT_importAnimation(bpy.types.Operator):
    bl_idname = "gf_model_tools.import_animation"
    bl_label = "Import Animation"
    bl_description = "Import the selected KEY animation onto the selected Grim armature"

    def execute(self, context):
        settings = GetAddonSettings(context)

        skeleton = None

        if settings.labPath != "" and settings.threeDoComponentId != "__NONE__":
            try:
                archive, _parsedCos, cosModel = GetSelectedCosModel(settings)
                threeDoArchive, threeDoEntry = FindLabEntryInRelatedLabs(archive, cosModel.name)

                if threeDoEntry is None:
                    raise ValueError(f"Could not find 3DO in selected LAB or sibling LABs: {cosModel.name}")

                model = Parse3DO(threeDoArchive.ReadEntry(threeDoEntry))
                skeleton = ModelToSkeleton(model)
            except Exception as error:
                self.report({"WARNING"}, f"Could not rebuild skeleton from 3DO: {error}")

        try:
            archive, _parsedCos, _cosModel = GetSelectedCosModel(settings)
            keyComponent = GetSelectedKeyComponent(settings)
            keyArchive, keyEntry, keyData = FindKeyEntryInRelatedLabs(archive, keyComponent.assetName)

            if keyEntry is None:
                raise ValueError(f"Could not find supported KEY in selected LAB or sibling LABs: {keyComponent.assetName}")

            targetFps = context.scene.render.fps if settings.animationUseSceneFps else 15

            action = ImportKeyAnimation(
                context,
                keyData,
                skeleton,
                targetFps,
                settings.animationImportMode,
                Path(keyComponent.assetName).stem,
            )
        except Exception as error:
            self.report({"ERROR"}, f"Could not import KEY: {error}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Imported animation: {action.name}")
        return {"FINISHED"}


class GF_MODEL_TOOLS_PT_mainPanel(bpy.types.Panel):
    bl_label = "GF Model Tools"
    bl_idname = "GF_MODEL_TOOLS_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GF Tools"

    def draw(self, context):
        settings = GetAddonSettings(context)
        layout = self.layout

        modelBox = layout.box()
        modelHeader = modelBox.row()
        modelHeader.prop(
            settings,
            "showModelImporter",
            text = "Model Importer",
            icon = "TRIA_DOWN" if settings.showModelImporter else "TRIA_RIGHT",
            emboss = False,
        )

        if settings.showModelImporter:
            modelBox.label(text = "Select LAB File:")
            modelBox.prop(settings, "labPath", text = "")
            modelBox.prop(settings, "cosName")
            modelBox.prop(settings, "threeDoComponentId")
            modelBox.prop(settings, "importSkeleton")
            applyPoseRow = modelBox.row()
            applyPoseRow.enabled = not settings.importSkeleton
            applyPoseRow.prop(settings, "applyPose")
            modelBox.separator()
            importRow = modelBox.row()
            importRow.enabled = IsImportReady(settings)
            importRow.operator(
                GF_MODEL_TOOLS_OT_extractThreeDo.bl_idname,
                text = "Import Model",
                icon = "IMPORT",
            )

        animationBox = layout.box()
        animationHeader = animationBox.row()
        animationHeader.prop(
            settings,
            "showAnimationImporter",
            text = "Animation Importer",
            icon = "TRIA_DOWN" if settings.showAnimationImporter else "TRIA_RIGHT",
            emboss = False,
        )

        if settings.showAnimationImporter:
            animationBox.prop(settings, "keyComponentId")
            animationBox.prop(settings, "animationImportMode")
            animationBox.prop(settings, "animationUseSceneFps")
            targetFps = context.scene.render.fps if settings.animationUseSceneFps else 15
            animationBox.label(text = f"Frame Scale: {targetFps / 15.0:.3f}")
            animationRow = animationBox.row()
            animationRow.enabled = IsAnimationReady(settings)
            animationRow.operator(
                GF_MODEL_TOOLS_OT_importAnimation.bl_idname,
                text = "Import Animation",
                icon = "ARMATURE_DATA",
            )


classes = (
    GF_MODEL_TOOLS_PG_settings,
    GF_MODEL_TOOLS_OT_selectLab,
    GF_MODEL_TOOLS_OT_selectThreeDo,
    GF_MODEL_TOOLS_OT_selectMatFolder,
    GF_MODEL_TOOLS_OT_selectCos,
    GF_MODEL_TOOLS_OT_selectKey,
    GF_MODEL_TOOLS_OT_extractThreeDo,
    GF_MODEL_TOOLS_OT_importAnimation,
    GF_MODEL_TOOLS_PT_mainPanel,
)


def register():
    for blenderClass in classes:
        bpy.utils.register_class(blenderClass)

    bpy.types.Scene.gfModelToolsSettings = bpy.props.PointerProperty(
        type = GF_MODEL_TOOLS_PG_settings,
    )


def unregister():
    del bpy.types.Scene.gfModelToolsSettings

    for blenderClass in reversed(classes):
        bpy.utils.unregister_class(blenderClass)


if __name__ == "__main__":
    register()
