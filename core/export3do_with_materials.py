from pathlib import Path
import argparse
import math
import struct


class BinaryReader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def ReadBytes(self, count):
        if self.offset + count > len(self.data):
            raise EOFError(f"Tried to read {count} bytes at {self.offset}, file size is {len(self.data)}")
        value = self.data[self.offset:self.offset + count]
        self.offset += count
        return value

    def ReadUInt32(self):
        value = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def ReadInt32(self):
        value = struct.unpack_from("<i", self.data, self.offset)[0]
        self.offset += 4
        return value

    def ReadFloat(self):
        value = struct.unpack_from("<f", self.data, self.offset)[0]
        self.offset += 4
        return value

    def ReadString32(self):
        raw = self.ReadBytes(32)
        return raw.split(b"\0", 1)[0].decode("latin-1", errors = "replace")

    def ReadString64(self):
        raw = self.ReadBytes(64)
        return raw.split(b"\0", 1)[0].decode("latin-1", errors = "replace")

    def Skip(self, count):
        if self.offset + count > len(self.data):
            raise EOFError(f"Tried to skip {count} bytes at {self.offset}, file size is {len(self.data)}")
        self.offset += count


def ReadUInt32At(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def ReadInputData(pathOrData):
    if isinstance(pathOrData, bytes):
        return pathOrData

    if isinstance(pathOrData, bytearray):
        return bytes(pathOrData)

    return Path(pathOrData).read_bytes()


def GetInputLabel(pathOrData):
    if isinstance(pathOrData, (bytes, bytearray)):
        return "<bytes>"

    return str(pathOrData)


def CleanMaterialName(name):
    name = Path(name).stem
    if name == "":
        return "default"
    return name.replace(" ", "_")


def IdentityMatrix():
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def TranslationMatrix(v):
    matrix = IdentityMatrix()
    matrix[0][3] = v[0]
    matrix[1][3] = v[1]
    matrix[2][3] = v[2]
    return matrix


def MatrixMultiply(a, b):
    out = [[0.0 for _ in range(4)] for _ in range(4)]

    for y in range(4):
        for x in range(4):
            out[y][x] = (
                a[y][0] * b[0][x] +
                a[y][1] * b[1][x] +
                a[y][2] * b[2][x] +
                a[y][3] * b[3][x]
            )

    return out


def TransformPoint(matrix, point):
    x, y, z = point

    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
    )


def RotationX(angle):
    c = math.cos(angle)
    s = math.sin(angle)
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, c, -s, 0.0],
        [0.0, s, c, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def RotationY(angle):
    c = math.cos(angle)
    s = math.sin(angle)
    return [
        [c, 0.0, s, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [-s, 0.0, c, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def RotationZ(angle):
    c = math.cos(angle)
    s = math.sin(angle)
    return [
        [c, -s, 0.0, 0.0],
        [s, c, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def EulerZXYMatrix(pitch, yaw, roll):
    rz = RotationZ(yaw)
    rx = RotationX(pitch)
    ry = RotationY(roll)
    return MatrixMultiply(MatrixMultiply(rz, rx), ry)


def LocalNodeMatrix(position, rotation):
    pitch, yaw, roll = rotation
    matrix = EulerZXYMatrix(pitch, yaw, roll)
    matrix[0][3] = position[0]
    matrix[1][3] = position[1]
    matrix[2][3] = position[2]
    return matrix


def ReadPalette(cmpPath):
    data = ReadInputData(cmpPath)

    if data[:4] != b"CMP ":
        raise ValueError("Not a CMP file")

    palette = []
    paletteOffset = 64

    for i in range(256):
        r = data[paletteOffset + i * 3 + 0]
        g = data[paletteOffset + i * 3 + 1]
        b = data[paletteOffset + i * 3 + 2]
        palette.append((r, g, b, 255))

    return palette


def GetMatDataOffsetExtra(data):
    dataOffsetExtra = ReadUInt32At(data, 0x4c)

    if dataOffsetExtra == 0x8:
        return 16

    if dataOffsetExtra != 0:
        raise ValueError(f"Unknown MAT offset value: {dataOffsetExtra}")

    return 0


def GetMatInfo(matPath):
    data = ReadInputData(matPath)
    inputLabel = GetInputLabel(matPath)

    if data[:4] != b"MAT ":
        raise ValueError(f"Not a MAT file: {inputLabel}")

    imageCount = ReadUInt32At(data, 12)
    offset = 60 + imageCount * 40 + GetMatDataOffsetExtra(data)

    images = []

    for imageIndex in range(imageCount):
        width = ReadUInt32At(data, offset)
        height = ReadUInt32At(data, offset + 4)
        hasAlpha = ReadUInt32At(data, offset + 8)
        offset += 24

        pixelCount = width * height
        if offset + pixelCount > len(data):
            raise ValueError(f"Not enough image data in {inputLabel} frame {imageIndex}")

        images.append({
            "width": width,
            "height": height,
            "hasAlpha": hasAlpha,
            "dataOffset": offset,
            "pixelCount": pixelCount,
        })

        offset += pixelCount

    return {
        "path": matPath,
        "imageCount": imageCount,
        "images": images,
    }


def ExportMatPngs(matPath, cmpPath, outputFolder):
    from PIL import Image

    matPath = Path(matPath)
    outputFolder = Path(outputFolder)
    outputFolder.mkdir(parents = True, exist_ok = True)

    data = matPath.read_bytes()
    palette = ReadPalette(cmpPath)
    info = GetMatInfo(matPath)
    outputPaths = []

    for imageIndex, imageInfo in enumerate(info["images"]):
        width = imageInfo["width"]
        height = imageInfo["height"]
        hasAlpha = imageInfo["hasAlpha"]
        dataOffset = imageInfo["dataOffset"]
        pixelCount = imageInfo["pixelCount"]

        indices = data[dataOffset:dataOffset + pixelCount]
        pixels = bytearray()

        for index in indices:
            r, g, b, a = palette[index]

            if hasAlpha != 0 and index == 0:
                a = 0

            pixels.extend((r, g, b, a))

        image = Image.frombytes("RGBA", (width, height), bytes(pixels))
        outPath = outputFolder / f"{matPath.stem}_{imageIndex:03}.png"
        image.save(outPath)
        outputPaths.append(outPath)

    return outputPaths, info


def Parse3DO(path):
    reader = BinaryReader(ReadInputData(path))

    magic = reader.ReadBytes(4)
    if magic != b"LDOM":
        raise ValueError("Not a binary LDOM 3DO file")

    materialCount = reader.ReadUInt32()
    materials = [reader.ReadString32() for _ in range(materialCount)]

    modelName = reader.ReadString32()
    reader.Skip(4)

    geosetCount = reader.ReadUInt32()
    meshes = []

    for _ in range(geosetCount):
        meshCount = reader.ReadUInt32()

        for _ in range(meshCount):
            meshName = reader.ReadString32()
            reader.Skip(4)

            geometryMode = reader.ReadUInt32()
            lightingMode = reader.ReadUInt32()
            textureMode = reader.ReadUInt32()

            vertexCount = reader.ReadUInt32()
            uvCount = reader.ReadUInt32()
            faceCount = reader.ReadUInt32()

            points = [(reader.ReadFloat(), reader.ReadFloat(), reader.ReadFloat()) for _ in range(vertexCount)]
            uvs = [(reader.ReadFloat(), reader.ReadFloat()) for _ in range(uvCount)]

            reader.Skip(vertexCount * 4)
            reader.Skip(vertexCount * 4)

            faces = []

            for _ in range(faceCount):
                reader.Skip(4)

                faceType = reader.ReadUInt32()
                faceGeo = reader.ReadUInt32()
                faceLight = reader.ReadUInt32()
                faceTex = reader.ReadUInt32()
                faceVertexCount = reader.ReadUInt32()

                reader.Skip(4)

                texPtr = reader.ReadUInt32()
                materialPtr = reader.ReadUInt32()

                reader.Skip(12)
                reader.Skip(4)
                reader.Skip(12)
                reader.Skip(12)

                vertexIndices = [reader.ReadUInt32() for _ in range(faceVertexCount)]

                uvIndices = None
                if texPtr != 0:
                    uvIndices = [reader.ReadUInt32() for _ in range(faceVertexCount)]

                materialIndex = -1
                if materialPtr != 0:
                    materialIndex = reader.ReadUInt32()

                faces.append({
                    "vertices": vertexIndices,
                    "uvs": uvIndices,
                    "material": materialIndex,
                    "faceType": faceType,
                    "faceGeo": faceGeo,
                    "faceLight": faceLight,
                    "faceTex": faceTex,
                })

            reader.Skip(vertexCount * 12)
            reader.Skip(4)
            reader.Skip(4)
            reader.Skip(4)
            reader.Skip(24)

            meshes.append({
                "name": meshName,
                "points": points,
                "uvs": uvs,
                "faces": faces,
                "geometryMode": geometryMode,
                "lightingMode": lightingMode,
                "textureMode": textureMode,
            })

    reader.Skip(4)

    nodeCount = reader.ReadUInt32()
    nodes = []

    for _ in range(nodeCount):
        nodeName = reader.ReadString64()

        flags = reader.ReadUInt32()
        reader.Skip(4)

        nodeType = reader.ReadUInt32()
        meshIndex = reader.ReadInt32()
        depth = reader.ReadUInt32()

        parentPtr = reader.ReadUInt32()
        childCount = reader.ReadUInt32()
        childPtr = reader.ReadUInt32()
        siblingPtr = reader.ReadUInt32()

        pivot = (reader.ReadFloat(), reader.ReadFloat(), reader.ReadFloat())
        position = (reader.ReadFloat(), reader.ReadFloat(), reader.ReadFloat())
        rotation = (reader.ReadFloat(), reader.ReadFloat(), reader.ReadFloat())

        reader.Skip(48)

        parent = reader.ReadInt32() if parentPtr != 0 else -1
        child = reader.ReadInt32() if childPtr != 0 else -1
        sibling = reader.ReadInt32() if siblingPtr != 0 else -1

        nodes.append({
            "name": nodeName,
            "meshIndex": meshIndex,
            "parent": parent,
            "child": child,
            "sibling": sibling,
            "childCount": childCount,
            "pivot": pivot,
            "position": position,
            "rotation": rotation,
            "localMatrix": IdentityMatrix(),
            "worldMatrix": IdentityMatrix(),
            "meshMatrix": IdentityMatrix(),
            "flags": flags,
            "nodeType": nodeType,
            "depth": depth,
        })

    for node in nodes:
        localMatrix = LocalNodeMatrix(node["position"], node["rotation"])
        node["localMatrix"] = localMatrix

        parent = node["parent"]
        if 0 <= parent < len(nodes):
            worldMatrix = MatrixMultiply(nodes[parent]["worldMatrix"], localMatrix)
        else:
            worldMatrix = localMatrix

        node["worldMatrix"] = worldMatrix
        node["meshMatrix"] = MatrixMultiply(worldMatrix, TranslationMatrix(node["pivot"]))

    radius = None
    insertOffset = (0.0, 0.0, 0.0)

    if reader.offset + 4 <= len(reader.data):
        radius = reader.ReadFloat()

    if reader.offset + 36 <= len(reader.data):
        reader.Skip(36)

    if reader.offset + 12 <= len(reader.data):
        insertOffset = (reader.ReadFloat(), reader.ReadFloat(), reader.ReadFloat())

    meshNodeByIndex = {}
    for node in nodes:
        meshIndex = node["meshIndex"]
        if 0 <= meshIndex < len(meshes):
            meshNodeByIndex[meshIndex] = node

    return {
        "modelName": modelName,
        "materials": materials,
        "meshes": meshes,
        "nodes": nodes,
        "meshNodeByIndex": meshNodeByIndex,
        "radius": radius,
        "insertOffset": insertOffset,
        "endOffset": reader.offset,
        "fileSize": len(reader.data),
    }



def ParseCosComponents(cosPath):
    cosPath = Path(cosPath)
    text = cosPath.read_text(encoding = "latin-1", errors = "replace")

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
            parts = line.split()

            if len(parts) >= 2 and parts[0].lstrip("-").isdigit():
                tagId = int(parts[0])
                tagName = parts[1].strip("'")
                tagNames[tagId] = tagName

        elif inComponents:
            parts = line.split(None, 4)

            if len(parts) >= 5 and parts[0].lstrip("-").isdigit():
                componentId = int(parts[0])
                tagId = int(parts[1])
                hashValue = int(parts[2])
                parentId = int(parts[3])
                name = parts[4].strip()

                components.append({
                    "id": componentId,
                    "tagId": tagId,
                    "tag": tagNames.get(tagId, ""),
                    "hash": hashValue,
                    "parentId": parentId,
                    "name": name,
                })

    return components


def ResolveCmpFromCos(cosPath, input3do, matFolder = None):
    cosPath = Path(cosPath)
    input3doName = Path(input3do).name.lower()
    components = ParseCosComponents(cosPath)

    modelComponent = None

    for component in components:
        componentName = component["name"].split(",", 1)[0].strip().lower()

        if componentName == input3doName and component["tag"] in ["MMDL", "MODL"]:
            modelComponent = component
            break

    if modelComponent is None:
        for component in components:
            componentName = component["name"].split(",", 1)[0].strip().lower()

            if componentName == input3doName:
                modelComponent = component
                break

    if modelComponent is None:
        raise ValueError(f"Could not find 3DO component in COS: {Path(input3do).name}")

    cmpComponent = None

    for component in components:
        if component["parentId"] == modelComponent["id"] and component["tag"] == "cmap":
            cmpComponent = component
            break

    if cmpComponent is None:
        for component in components:
            if component["parentId"] == modelComponent["id"] and component["name"].lower().endswith(".cmp"):
                cmpComponent = component
                break

    if cmpComponent is None:
        raise ValueError(f"Could not find CMP component parented to {modelComponent['name']} in COS")

    cmpName = cmpComponent["name"].split(",", 1)[0].strip()
    searchFolders = [cosPath.parent]

    if matFolder is not None:
        searchFolders.append(Path(matFolder))

    searchFolders.append(Path.cwd())

    for folder in searchFolders:
        cmpPath = folder / cmpName
        if cmpPath.exists():
            return cmpPath, cmpName

    return cosPath.parent / cmpName, cmpName

def BuildMaterialInfo(materials, matFolder, cmpPath, textureOutputFolder):
    matFolder = Path(matFolder)
    textureOutputFolder = Path(textureOutputFolder)
    materialInfo = []

    for material in materials:
        materialName = CleanMaterialName(material)
        matPath = matFolder / material

        if not matPath.exists():
            matPath = matFolder / f"{materialName}.mat"

        info = {
            "name": materialName,
            "matPath": matPath,
            "width": 64,
            "height": 64,
            "texturePath": None,
            "found": False,
        }

        if matPath.exists():
            outputPaths, matInfo = ExportMatPngs(matPath, cmpPath, textureOutputFolder)
            firstImage = matInfo["images"][0]

            info["width"] = firstImage["width"]
            info["height"] = firstImage["height"]
            info["texturePath"] = outputPaths[0]
            info["found"] = True

        materialInfo.append(info)

    return materialInfo


def ConvertUv(u, v, width, height, flipV = False):
    outU = u / width if width != 0 else u
    outV = -v / height if height != 0 else -v

    if flipV:
        outV = 1.0 - outV

    return outU, outV


def WriteOBJ(path, model, materialInfo, flipV = False, applyHierarchy = True):
    path = Path(path)
    path.parent.mkdir(parents = True, exist_ok = True)
    mtlPath = path.with_suffix(".mtl")

    materials = model["materials"]
    meshes = model["meshes"]
    meshNodeByIndex = model["meshNodeByIndex"]

    with open(mtlPath, "w", encoding = "utf-8", newline = "\n") as file:
        for info in materialInfo:
            file.write(f"newmtl {info['name']}\n")
            file.write("Kd 1.0 1.0 1.0\n")

            if info["texturePath"] is not None:
                relativeTexturePath = Path(info["texturePath"]).relative_to(mtlPath.parent).as_posix()
                file.write(f"map_Kd {relativeTexturePath}\n")

            file.write("\n")

        file.write("newmtl default\n")
        file.write("Kd 1.0 1.0 1.0\n\n")

    with open(path, "w", encoding = "utf-8", newline = "\n") as file:
        file.write(f"# Converted from {model['modelName']}\n")
        file.write(f"mtllib {mtlPath.name}\n")
        file.write("# 3DO UVs are divided by each material's MAT texture size.\n\n")

        vertexOffset = 1
        uvOffset = 1

        for meshIndex, mesh in enumerate(meshes):
            points = mesh["points"]
            faces = mesh["faces"]

            if len(points) == 0:
                continue

            matrix = IdentityMatrix()
            if applyHierarchy and meshIndex in meshNodeByIndex:
                matrix = meshNodeByIndex[meshIndex]["meshMatrix"]

            file.write(f"o {mesh['name']}\n")

            for point in points:
                x, y, z = TransformPoint(matrix, point)
                file.write(f"v {x:.9g} {y:.9g} {z:.9g}\n")

            currentMaterial = None

            for face in faces:
                materialIndex = face["material"]

                if materialIndex != currentMaterial:
                    currentMaterial = materialIndex

                    if 0 <= materialIndex < len(materials):
                        file.write(f"usemtl {CleanMaterialName(materials[materialIndex])}\n")
                    else:
                        file.write("usemtl default\n")

                vertexIndices = face["vertices"]
                uvIndices = face["uvs"]
                faceUvObjIndices = []

                if uvIndices is not None and 0 <= materialIndex < len(materialInfo):
                    info = materialInfo[materialIndex]
                    width = float(info["width"])
                    height = float(info["height"])

                    for uvIndex in uvIndices:
                        if 0 <= uvIndex < len(mesh["uvs"]):
                            u, v = mesh["uvs"][uvIndex]
                            u, v = ConvertUv(u, v, width, height, flipV = flipV)
                            file.write(f"vt {u:.9g} {v:.9g}\n")
                            faceUvObjIndices.append(uvOffset)
                            uvOffset += 1
                        else:
                            faceUvObjIndices.append(None)

                parts = []

                for i, vertexIndex in enumerate(vertexIndices):
                    objVertexIndex = vertexOffset + vertexIndex

                    if i < len(faceUvObjIndices) and faceUvObjIndices[i] is not None:
                        parts.append(f"{objVertexIndex}/{faceUvObjIndices[i]}")
                    else:
                        parts.append(str(objVertexIndex))

                file.write("f " + " ".join(parts) + "\n")

            vertexOffset += len(points)
            file.write("\n")


def WriteSkeletonJson(path, model):
    import json

    path = Path(path)
    path.parent.mkdir(parents = True, exist_ok = True)

    bones = []

    for nodeIndex, node in enumerate(model["nodes"]):
        bones.append({
            "index": nodeIndex,
            "name": node["name"],
            "parent": node["parent"],
            "meshIndex": node["meshIndex"],
            "pivot": node["pivot"],
            "position": node["position"],
            "rotation": node["rotation"],
            "localMatrix": node["localMatrix"],
            "worldMatrix": node["worldMatrix"],
            "meshMatrix": node["meshMatrix"],
        })

    data = {
        "modelName": model["modelName"],
        "bones": bones,
    }

    with open(path, "w", encoding = "utf-8", newline = "\n") as file:
        json.dump(data, file, indent = 4)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input3do")
    parser.add_argument("matFolder")
    parser.add_argument("cos")
    parser.add_argument("outputObj")
    parser.add_argument("--textureFolder", default = "textures")
    parser.add_argument("--flipV", action = "store_true")
    parser.add_argument("--noHierarchy", action = "store_true", help = "Do not bake node hierarchy transforms into OBJ vertices")
    parser.add_argument("--noTransform", action = "store_true", help = "Alias for --noHierarchy: export mesh vertices in local component space")
    args = parser.parse_args()

    outputObj = Path(args.outputObj)
    textureOutputFolder = outputObj.parent / args.textureFolder

    model = Parse3DO(args.input3do)
    cmpPath, cmpName = ResolveCmpFromCos(args.cos, args.input3do, args.matFolder)
    materialInfo = BuildMaterialInfo(model["materials"], args.matFolder, cmpPath, textureOutputFolder)

    WriteOBJ(
        path = outputObj,
        model = model,
        materialInfo = materialInfo,
        flipV = args.flipV,
        applyHierarchy = not (args.noHierarchy or args.noTransform),
    )

    skeletonPath = outputObj.with_suffix(".skeleton.json")
    WriteSkeletonJson(skeletonPath, model)
    print("wrote skeleton:", skeletonPath)

    print("geometry transforms:", "baked into OBJ" if not (args.noHierarchy or args.noTransform) else "not baked; local component-space vertices")
    print("model:", model["modelName"])
    print("cmp:", cmpName)
    print("cmp path:", cmpPath)
    print("materials:", len(model["materials"]))
    print("meshes:", len(model["meshes"]))
    print("nodes:", len(model["nodes"]))
    print("radius:", model["radius"])
    print("insert offset:", model["insertOffset"])
    print("end offset:", model["endOffset"], "/", model["fileSize"])

    for info in materialInfo:
        status = "found" if info["found"] else "missing, using 64x64 fallback"
        print(f"material: {info['name']} {info['width']}x{info['height']} {status}")

    print("wrote:", outputObj)


if __name__ == "__main__":
    main()
