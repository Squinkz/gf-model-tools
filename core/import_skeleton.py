import bpy
import json
from mathutils import Matrix, Vector


def CleanBlenderName(name):
    if len(name) > 4 and name[-4] == "." and name[-3:].isdigit():
        return name[:-4]

    return name


def JsonMatrixToBlender(matrix):
    return Matrix((
        (matrix[0][0], matrix[0][1], matrix[0][2], matrix[0][3]),
        (matrix[1][0], matrix[1][1], matrix[1][2], matrix[1][3]),
        (matrix[2][0], matrix[2][1], matrix[2][2], matrix[2][3]),
        (matrix[3][0], matrix[3][1], matrix[3][2], matrix[3][3]),
    ))


def ModelToSkeleton(model):
    bones = []

    for index, node in enumerate(model["nodes"]):
        bones.append({
            "index": index,
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

    return {
        "modelName": model["modelName"],
        "bones": bones,
    }


def GetNodePosition(bone):
    matrix = bone["worldMatrix"]

    return Vector((
        matrix[0][3],
        matrix[1][3],
        matrix[2][3],
    ))


def GetBoneTail(index, bone, bones, childrenByParent):
    head = GetNodePosition(bone)

    pivot = Vector((
        bone["pivot"][0],
        bone["pivot"][1],
        bone["pivot"][2],
    ))

    if pivot.length >= 0.001:
        return head + pivot.normalized() * 0.025

    childIndices = childrenByParent.get(index, [])

    if len(childIndices) == 1:
        child = bones[childIndices[0]]
        tail = GetNodePosition(child)

        if (tail - head).length >= 0.001 and (tail - head).length <= 0.12:
            return tail

    return head + Vector((0.0, 0.0, 0.025))


def BuildChildrenByParent(bones):
    childrenByParent = {}

    for bone in bones:
        parent = bone["parent"]

        if parent not in childrenByParent:
            childrenByParent[parent] = []

        childrenByParent[parent].append(bone["index"])

    return childrenByParent


def CreateArmature(skeleton):
    bones = skeleton["bones"]
    childrenByParent = BuildChildrenByParent(bones)

    bpy.ops.object.armature_add(enter_editmode = True, location = (0, 0, 0))

    armatureObject = bpy.context.object
    armatureObject.name = skeleton["modelName"] + "_Armature"
    armatureObject.data.name = skeleton["modelName"] + "_Skeleton"
    skeletonJson = json.dumps(skeleton)
    armatureObject["grimSkeletonJson"] = skeletonJson
    armatureObject.data["grimSkeletonJson"] = skeletonJson

    editBones = armatureObject.data.edit_bones

    for editBone in list(editBones):
        editBones.remove(editBone)

    createdBones = {}

    for bone in bones:
        name = bone["name"]
        index = bone["index"]

        head = GetNodePosition(bone)
        tail = GetBoneTail(index, bone, bones, childrenByParent)

        editBone = editBones.new(name)
        editBone.head = head
        editBone.tail = tail
        editBone.roll = 0.0

        createdBones[index] = editBone

    for bone in bones:
        index = bone["index"]
        parentIndex = bone["parent"]

        if parentIndex >= 0:
            createdBones[index].parent = createdBones[parentIndex]
            createdBones[index].use_connect = False

    for bone in bones:
        index = bone["index"]
        editBone = createdBones[index]

        direction = editBone.tail - editBone.head

        if direction.length < 0.001:
            continue

        name = bone["name"].lower()

        if (
            "thumb" in name or
            "index" in name or
            "mid" in name or
            "pinky" in name or
            "toe" in name or
            "heel" in name
        ):
            editBone.align_roll(Vector((0.0, 1.0, 0.0)))
        else:
            editBone.align_roll(Vector((0.0, 0.0, 1.0)))

    bpy.ops.object.mode_set(mode = "OBJECT")
    bpy.context.scene.frame_set(0)
    armatureObject.data.pose_position = "REST"
    bpy.context.view_layer.update()

    for bone in bones:
        boneData = armatureObject.data.bones.get(bone["name"])

        if boneData is None:
            continue

        boneData["grimNodeIndex"] = bone["index"]
        boneData["grimParentIndex"] = bone["parent"]
        boneData["grimMeshIndex"] = bone["meshIndex"]
        boneData["grimPivot"] = json.dumps(bone["pivot"])
        boneData["grimPosition"] = json.dumps(bone["position"])
        boneData["grimRotation"] = json.dumps(bone["rotation"])
        boneData["grimLocalMatrix"] = json.dumps(bone["localMatrix"])
        boneData["grimWorldMatrix"] = json.dumps(bone["worldMatrix"])
        boneData["grimMeshMatrix"] = json.dumps(bone["meshMatrix"])

    return armatureObject


def AttachMeshesToArmature(armatureObject, skeleton, meshObjects):
    bones = skeleton["bones"]

    boneNames = set(armatureObject.data.bones.keys())
    boneDataByName = {}
    boneDataByMeshIndex = {}
    attachedCount = 0

    for bone in bones:
        boneDataByName[bone["name"]] = bone

        if bone["meshIndex"] >= 0:
            boneDataByMeshIndex[bone["meshIndex"]] = bone

    for obj in meshObjects:
        if obj.type != "MESH":
            continue

        meshName = CleanBlenderName(obj.name)
        meshIndex = obj.get("grimMeshIndex", -1)
        boneData = None

        if meshIndex in boneDataByMeshIndex:
            boneData = boneDataByMeshIndex[meshIndex]
            boneName = boneData["name"]
        else:
            boneName = meshName

            if boneName not in boneNames:
                print("No matching bone for mesh object:", obj.name, "->", meshName)
                continue

            if boneName not in boneDataByName:
                print("No skeleton data for bone:", boneName)
                continue

            boneData = boneDataByName[boneName]

        meshWorldMatrix = JsonMatrixToBlender(boneData["meshMatrix"])
        boneRestWorldMatrix = (
            armatureObject.matrix_world @
            armatureObject.data.bones[boneName].matrix_local
        )

        obj.matrix_world = meshWorldMatrix
        bpy.context.view_layer.update()

        obj.parent = armatureObject
        obj.parent_type = "BONE"
        obj.parent_bone = boneName
        obj.matrix_parent_inverse = boneRestWorldMatrix.inverted()

        obj.matrix_world = meshWorldMatrix
        bpy.context.view_layer.update()

        attachedCount += 1
        print("Attached mesh to bone:", obj.name, "->", boneName)

    armatureObject.data.pose_position = "POSE"
    bpy.context.view_layer.update()

    return attachedCount


def ImportSkeleton(model, meshObjects):
    skeleton = ModelToSkeleton(model)
    armatureObject = CreateArmature(skeleton)
    attachedCount = AttachMeshesToArmature(armatureObject, skeleton, meshObjects)

    print("Imported skeleton:", skeleton["modelName"])
    print("Bones:", len(skeleton["bones"]))
    print("Attached meshes:", attachedCount)

    return armatureObject
