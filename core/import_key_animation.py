import json
import math
import re
import struct
from pathlib import Path

import bpy
from mathutils import Matrix


def ReadString(data, offset, length):
    raw = data[offset:offset + length]
    return raw.split(b"\0", 1)[0].decode("latin-1")


def ReadInputData(pathOrData):
    if isinstance(pathOrData, bytes):
        return pathOrData

    if isinstance(pathOrData, bytearray):
        return bytes(pathOrData)

    return Path(pathOrData).read_bytes()


def GetInputName(pathOrData, fallbackName = "animation"):
    if isinstance(pathOrData, (bytes, bytearray)):
        return fallbackName

    return Path(pathOrData).stem


def ParseKey(pathOrData):
    data = ReadInputData(pathOrData)

    if data[0:4] != b"FYEK":
        return ParseTextKey(data)

    name = ReadString(data, 4, 36)
    headerFlags = struct.unpack_from("<I", data, 0x28)[0]
    animType = struct.unpack_from("<I", data, 0x30)[0]
    frameCount = struct.unpack_from("<I", data, 0x38)[0]
    fps = struct.unpack_from("<f", data, 0x34)[0]
    jointCount = struct.unpack_from("<I", data, 0x3c)[0]

    offset = 0x88
    tracks = []

    for _ in range(jointCount):
        if offset + 44 > len(data):
            break

        nodeName = ReadString(data, offset, 32)
        nodeIndex = struct.unpack_from("<I", data, offset + 32)[0]
        entryCount = struct.unpack_from("<I", data, offset + 36)[0]
        unknown = struct.unpack_from("<I", data, offset + 40)[0]
        offset += 44
        entries = []

        for _ in range(entryCount):
            if offset + 56 > len(data):
                raise ValueError(f"KEY entry runs past end of file at offset {offset}")

            (
                frame,
                entryFlags,
                posX,
                posY,
                posZ,
                pitch,
                yaw,
                roll,
                dPosX,
                dPosY,
                dPosZ,
                dPitch,
                dYaw,
                dRoll,
            ) = struct.unpack_from("<fI12f", data, offset)

            offset += 56

            entries.append({
                "frame": frame,
                "flags": entryFlags,
                "position": (posX, posY, posZ),
                "rotation": (pitch, yaw, roll),
                "deltaPosition": (dPosX, dPosY, dPosZ),
                "deltaRotation": (dPitch, dYaw, dRoll),
            })

        tracks.append({
            "name": nodeName,
            "nodeIndex": nodeIndex,
            "unknown": unknown,
            "entries": entries,
        })

    return {
        "name": name,
        "flags": headerFlags,
        "type": animType,
        "fps": fps,
        "frameCount": frameCount,
        "jointCount": jointCount,
        "tracks": tracks,
    }


def ParseTextKey(data):
    text = data.decode("latin-1", errors = "replace")
    lines = text.splitlines()

    if "section: header" not in text.lower():
        raise ValueError("Not a Grim KEY file")

    firstLine = lines[0].strip() if len(lines) > 0 else ""
    name = "animation"
    nameMatch = re.search(r"'([^']+)'", firstLine)

    if nameMatch is not None:
        name = nameMatch.group(1)

    headerLines = GetSectionLines(lines, "header")
    markerLines = GetSectionLines(lines, "markers")
    nodeLines = GetSectionLines(lines, "keyframe nodes")
    header = ParseTextKeyHeader(headerLines)
    markers = ParseTextKeyMarkers(markerLines)
    tracks = ParseTextKeyNodes(nodeLines)

    return {
        "name": name,
        "flags": header.get("flags", 0),
        "type": header.get("type", 0),
        "fps": header.get("fps", 15.0),
        "frameCount": header.get("frames", 0),
        "jointCount": header.get("joints", 0),
        "markers": markers,
        "tracks": tracks,
    }


def GetSectionLines(lines, sectionName):
    sectionHeader = f"section: {sectionName}".lower()
    startIndex = None

    for index, rawLine in enumerate(lines):
        if rawLine.strip().lower() == sectionHeader:
            startIndex = index + 1
            break

    if startIndex is None:
        return []

    endIndex = len(lines)

    for index in range(startIndex, len(lines)):
        if lines[index].strip().lower().startswith("section: "):
            endIndex = index
            break

    return lines[startIndex:endIndex]


def IterMeaningfulLines(lines):
    for rawLine in lines:
        line = rawLine.strip()

        if line == "" or line.startswith("#"):
            continue

        yield line


def ParseTextKeyHeader(lines):
    header = {}

    for line in IterMeaningfulLines(lines):
        parts = line.split()

        if len(parts) < 2:
            continue

        key = parts[0].lower()
        value = parts[1]

        if key in ("flags", "type"):
            header[key] = int(value, 16)
        elif key in ("frames", "joints"):
            header[key] = int(value)
        elif key == "fps":
            header[key] = float(value)

    return header


def ParseTextKeyMarkers(lines):
    markers = []
    readingMarkers = False

    for line in IterMeaningfulLines(lines):
        parts = line.split()

        if len(parts) == 0:
            continue

        if parts[0].lower() == "markers":
            readingMarkers = True
            continue

        if readingMarkers and len(parts) >= 2:
            markers.append({
                "frame": float(parts[0]),
                "value": int(parts[1]),
            })

    return markers


def ParseTextKeyNodes(lines):
    usefulLines = list(IterMeaningfulLines(lines))
    tracks = []
    index = 0

    while index < len(usefulLines):
        line = usefulLines[index]
        parts = line.split()

        if len(parts) >= 2 and parts[0].lower() == "nodes":
            index += 1
            continue

        if len(parts) < 2 or parts[0].lower() != "node":
            index += 1
            continue

        nodeIndex = int(parts[1])
        index += 1
        nodeName = ""
        entryCount = 0

        if index < len(usefulLines) and usefulLines[index].lower().startswith("mesh name"):
            nodeName = usefulLines[index][len("mesh name"):].strip()
            index += 1

        if index < len(usefulLines):
            entryParts = usefulLines[index].split()

            if len(entryParts) >= 2 and entryParts[0].lower() == "entries":
                entryCount = int(entryParts[1])
                index += 1

        entries = []

        while index < len(usefulLines) and len(entries) < entryCount:
            if ":" not in usefulLines[index]:
                index += 1
                continue

            mainLine = usefulLines[index]
            index += 1

            if index >= len(usefulLines):
                raise ValueError(f"Text KEY entry missing delta line for node {nodeIndex}")

            deltaLine = usefulLines[index]
            index += 1
            entries.append(ParseTextKeyEntry(mainLine, deltaLine))

        tracks.append({
            "name": nodeName,
            "nodeIndex": nodeIndex,
            "unknown": 0,
            "entries": entries,
        })

    return tracks


def ParseTextKeyEntry(mainLine, deltaLine):
    _entryNumber, rest = mainLine.split(":", 1)
    mainParts = rest.split()
    deltaParts = deltaLine.split()

    if len(mainParts) < 8 or len(deltaParts) < 6:
        raise ValueError(f"Malformed text KEY entry: {mainLine}")

    return {
        "frame": float(mainParts[0]),
        "flags": int(mainParts[1], 16),
        "position": (
            float(mainParts[2]),
            float(mainParts[3]),
            float(mainParts[4]),
        ),
        "rotation": (
            float(mainParts[5]),
            float(mainParts[6]),
            float(mainParts[7]),
        ),
        "deltaPosition": (
            float(deltaParts[0]),
            float(deltaParts[1]),
            float(deltaParts[2]),
        ),
        "deltaRotation": (
            float(deltaParts[3]),
            float(deltaParts[4]),
            float(deltaParts[5]),
        ),
    }


def JsonMatrixToBlender(matrix):
    return Matrix((
        (matrix[0][0], matrix[0][1], matrix[0][2], matrix[0][3]),
        (matrix[1][0], matrix[1][1], matrix[1][2], matrix[1][3]),
        (matrix[2][0], matrix[2][1], matrix[2][2], matrix[2][3]),
        (matrix[3][0], matrix[3][1], matrix[3][2], matrix[3][3]),
    ))


def RotationX(angle):
    c = math.cos(angle)
    s = math.sin(angle)

    return Matrix((
        (1.0, 0.0, 0.0, 0.0),
        (0.0, c, -s, 0.0),
        (0.0, s, c, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ))


def RotationY(angle):
    c = math.cos(angle)
    s = math.sin(angle)

    return Matrix((
        (c, 0.0, s, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (-s, 0.0, c, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ))


def RotationZ(angle):
    c = math.cos(angle)
    s = math.sin(angle)

    return Matrix((
        (c, -s, 0.0, 0.0),
        (s, c, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ))


def GrimLocalMatrix(position, rotation):
    pitch, yaw, roll = rotation
    pitch = math.radians(pitch)
    yaw = math.radians(yaw)
    roll = math.radians(roll)

    matrix = RotationZ(yaw) @ RotationX(pitch) @ RotationY(roll)
    matrix[0][3] = position[0]
    matrix[1][3] = position[1]
    matrix[2][3] = position[2]
    return matrix


def AddVector(a, b):
    return (
        a[0] + b[0],
        a[1] + b[1],
        a[2] + b[2],
    )


def ScaleVector(value, scale):
    return (
        value[0] * scale,
        value[1] * scale,
        value[2] * scale,
    )


def EvaluateTrack(track, frame, useDelta):
    entries = track["entries"]

    if len(entries) == 0:
        return None

    bestEntry = entries[0]

    for entry in entries:
        if entry["frame"] <= frame:
            bestEntry = entry
        else:
            break

    dt = frame - bestEntry["frame"]

    if not useDelta:
        dt = 0.0

    return {
        "position": AddVector(
            bestEntry["position"],
            ScaleVector(bestEntry["deltaPosition"], dt),
        ),
        "rotation": AddVector(
            bestEntry["rotation"],
            ScaleVector(bestEntry["deltaRotation"], dt),
        ),
    }


def BuildAnimatedLocalMatrices(skeleton, trackByIndex, frame, useDelta):
    localMatrixByIndex = {}
    evaluatedByIndex = {}

    for bone in skeleton["bones"]:
        index = bone["index"]
        track = trackByIndex.get(index)
        evaluated = None

        if track is not None:
            evaluated = EvaluateTrack(track, frame, useDelta)

        if evaluated is not None:
            position = evaluated["position"]
            rotation = evaluated["rotation"]
            evaluatedByIndex[index] = evaluated
        else:
            position = bone["position"]
            rotation = bone["rotation"]

        localMatrixByIndex[index] = GrimLocalMatrix(position, rotation)

    return localMatrixByIndex, evaluatedByIndex


def BuildWorldMatrices(skeleton, localMatrixByIndex):
    worldMatrixByIndex = {}

    for bone in skeleton["bones"]:
        index = bone["index"]
        parentIndex = bone["parent"]
        localMatrix = localMatrixByIndex[index]

        if parentIndex >= 0 and parentIndex in worldMatrixByIndex:
            worldMatrixByIndex[index] = worldMatrixByIndex[parentIndex] @ localMatrix
        else:
            worldMatrixByIndex[index] = localMatrix.copy()

    return worldMatrixByIndex


def SetSceneFrame(frame):
    wholeFrame = math.floor(frame)
    subFrame = frame - wholeFrame
    bpy.context.scene.frame_set(wholeFrame, subframe = subFrame)


def GetArmature(context):
    activeObject = context.view_layer.objects.active

    if activeObject is not None and activeObject.type == "ARMATURE":
        return activeObject

    for obj in context.selected_objects:
        if obj.type == "ARMATURE":
            return obj

    for obj in context.scene.objects:
        if (
            obj.type == "ARMATURE" and
            ("grimSkeletonJson" in obj or "grimSkeletonJson" in obj.data)
        ):
            return obj

    return None


def MatrixToList(matrix):
    return [
        [matrix[row][col] for col in range(4)]
        for row in range(4)
    ]


def GetBoneJsonProperty(bone, name, defaultValue):
    if name not in bone:
        return defaultValue

    return json.loads(bone[name])


def GetBoneIntProperty(bone, name, defaultValue):
    if name not in bone:
        return defaultValue

    return int(bone[name])


def BuildSkeletonFromBoneProperties(armatureObject):
    bones = []

    for bone in armatureObject.data.bones:
        if "grimNodeIndex" not in bone:
            continue

        index = int(bone["grimNodeIndex"])

        while len(bones) <= index:
            bones.append(None)

        bones[index] = {
            "index": index,
            "name": bone.name,
            "parent": GetBoneIntProperty(bone, "grimParentIndex", -1),
            "meshIndex": GetBoneIntProperty(bone, "grimMeshIndex", -1),
            "pivot": GetBoneJsonProperty(bone, "grimPivot", (0.0, 0.0, 0.0)),
            "position": GetBoneJsonProperty(bone, "grimPosition", (0.0, 0.0, 0.0)),
            "rotation": GetBoneJsonProperty(bone, "grimRotation", (0.0, 0.0, 0.0)),
            "localMatrix": GetBoneJsonProperty(bone, "grimLocalMatrix", MatrixToList(bone.matrix_local)),
            "worldMatrix": GetBoneJsonProperty(bone, "grimWorldMatrix", MatrixToList(bone.matrix_local)),
            "meshMatrix": GetBoneJsonProperty(bone, "grimMeshMatrix", MatrixToList(bone.matrix_local)),
        }

    bones = [bone for bone in bones if bone is not None]

    if len(bones) == 0:
        raise ValueError("Selected armature does not contain Grim skeleton data")

    return {
        "modelName": armatureObject.name,
        "bones": bones,
    }


def StoreSkeletonOnArmature(armatureObject, skeleton):
    skeletonJson = json.dumps(skeleton)
    armatureObject["grimSkeletonJson"] = skeletonJson
    armatureObject.data["grimSkeletonJson"] = skeletonJson


def GetSkeletonFromArmature(armatureObject):
    if "grimSkeletonJson" in armatureObject:
        return json.loads(armatureObject["grimSkeletonJson"])

    if "grimSkeletonJson" in armatureObject.data:
        return json.loads(armatureObject.data["grimSkeletonJson"])

    return BuildSkeletonFromBoneProperties(armatureObject)


def BuildSourceFrames(importMode, keySourceFrames, actualFrameEnd, frameScale):
    if importMode == "SAMPLED":
        blenderFrameEnd = math.ceil(actualFrameEnd * frameScale)

        return [
            blenderFrame / frameScale
            for blenderFrame in range(0, blenderFrameEnd + 1)
        ]

    return keySourceFrames


def GetOrCreateImportAction(actionName):
    action = bpy.data.actions.get(actionName)

    if action is None:
        action = bpy.data.actions.new(actionName)
    else:
        while len(action.fcurves) > 0:
            action.fcurves.remove(action.fcurves[0])

        while len(action.groups) > 0:
            action.groups.remove(action.groups[0])

        while len(action.pose_markers) > 0:
            action.pose_markers.remove(action.pose_markers[0])

    action.use_fake_user = True
    action["grimKeyAnimation"] = True
    return action


def ImportKeyAnimation(context, keyPath, skeleton = None, targetFps = None, importMode = "KEYFRAMES", actionName = None):
    engineFps = 15
    frameOffset = 1

    if targetFps is None:
        targetFps = context.scene.render.fps

    frameScale = targetFps / engineFps
    animation = ParseKey(keyPath)
    useDelta = (animation["flags"] & 0x100) == 0
    armatureObject = GetArmature(context)

    if armatureObject is None:
        raise ValueError("Select a Grim armature before importing a KEY animation")

    if "grimSkeletonJson" in armatureObject or "grimSkeletonJson" in armatureObject.data:
        skeleton = GetSkeletonFromArmature(armatureObject)
    elif skeleton is not None:
        StoreSkeletonOnArmature(armatureObject, skeleton)
    else:
        skeleton = GetSkeletonFromArmature(armatureObject)

    bpy.ops.object.mode_set(mode = "OBJECT")

    for obj in context.scene.objects:
        obj.select_set(False)

    context.view_layer.objects.active = armatureObject
    armatureObject.select_set(True)
    bpy.ops.object.mode_set(mode = "POSE")

    boneByIndex = {}

    for bone in skeleton["bones"]:
        index = bone["index"]
        name = bone["name"]

        if name in armatureObject.pose.bones:
            boneByIndex[index] = armatureObject.pose.bones[name]
        else:
            print("Skeleton bone missing from armature:", index, name)

    animatedTracks = [track for track in animation["tracks"] if len(track["entries"]) > 0]

    if len(animatedTracks) == 0:
        raise ValueError(f"KEY file has no animated tracks: {GetInputName(keyPath)}")

    actualFrameEnd = max(
        entry["frame"]
        for track in animatedTracks
        for entry in track["entries"]
    )

    context.scene.frame_start = frameOffset
    context.scene.frame_end = math.ceil(actualFrameEnd * frameScale) + frameOffset

    if actionName is None:
        actionName = GetInputName(keyPath)

    action = GetOrCreateImportAction(actionName)
    armatureObject.animation_data_create()
    armatureObject.animation_data.action = action

    trackByIndex = {}
    grimRestWorldByIndex = {}
    blenderRestWorldByIndex = {}

    for track in animatedTracks:
        trackByIndex[track["nodeIndex"]] = track

    for bone in skeleton["bones"]:
        index = bone["index"]
        grimRestWorldByIndex[index] = JsonMatrixToBlender(bone["worldMatrix"])

        if index in boneByIndex:
            blenderRestWorldByIndex[index] = armatureObject.data.bones[bone["name"]].matrix_local.copy()

    keySourceFrames = sorted({
        entry["frame"]
        for track in animatedTracks
        for entry in track["entries"]
    })
    sourceFrames = BuildSourceFrames(
        importMode,
        keySourceFrames,
        actualFrameEnd,
        frameScale,
    )

    insertedKeyframes = 0
    missingTrackBones = []

    for sourceFrame in sourceFrames:
        blenderFrame = frameOffset + (sourceFrame * frameScale)
        SetSceneFrame(blenderFrame)

        localMatrixByIndex, evaluatedByIndex = BuildAnimatedLocalMatrices(
            skeleton,
            trackByIndex,
            sourceFrame,
            useDelta,
        )
        grimTargetWorldByIndex = BuildWorldMatrices(skeleton, localMatrixByIndex)

        for bone in skeleton["bones"]:
            nodeIndex = bone["index"]
            poseBone = boneByIndex.get(nodeIndex)

            if poseBone is None:
                if nodeIndex in evaluatedByIndex and nodeIndex not in missingTrackBones:
                    missingTrackBones.append(nodeIndex)
                continue

            targetBoneMatrix = (
                grimTargetWorldByIndex[nodeIndex] @
                grimRestWorldByIndex[nodeIndex].inverted() @
                blenderRestWorldByIndex[nodeIndex]
            )

            poseBone.rotation_mode = "QUATERNION"
            poseBone.matrix = targetBoneMatrix
            context.view_layer.update()
            poseBone.keyframe_insert(data_path = "location", frame = blenderFrame)
            poseBone.keyframe_insert(data_path = "rotation_quaternion", frame = blenderFrame)
            insertedKeyframes += 2

    if armatureObject.animation_data and armatureObject.animation_data.action:
        for fcurve in armatureObject.animation_data.action.fcurves:
            for keyframe in fcurve.keyframe_points:
                keyframe.interpolation = "LINEAR"

    bpy.ops.object.mode_set(mode = "OBJECT")

    print("Applied KEY:", animation["name"])
    print("Action:", actionName)
    print("Stored KEY FPS:", animation["fps"])
    print("Engine FPS:", engineFps)
    print("Blender FPS:", targetFps)
    print("Frame scale:", frameScale)
    print("Import mode:", importMode)
    print("KEY flags:", hex(animation["flags"]))
    print("Using deltas:", useDelta)
    print("Frames:", animation["frameCount"])
    print("KEY header joint count:", animation["jointCount"])
    print("KEY parsed tracks:", len(animation["tracks"]))
    print("Animated tracks:", len(animatedTracks))
    print("Inserted keyframes:", insertedKeyframes)

    if len(missingTrackBones) > 0:
        print("Animated tracks without matching bones:", missingTrackBones)

    return action
