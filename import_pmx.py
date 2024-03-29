# coding: utf-8
"""
PMDはPMXに変換してからインポートする。
"""
from typing import Tuple, Optional
from .pymeshio import pmx
import os

if "bpy" in locals():
    import importlib

    importlib.reload(bl)  # type: ignore

import bpy  # type: ignore
import bpy_extras  # type: ignore
import mathutils  # type: ignore
from . import bl

UV_NAME = "uv0"


def assignVertexGroup(o, name, index, weight):
    if name not in o.vertex_groups:
        o.vertex_groups.new(name=name)
    o.vertex_groups[name].add([index], weight, "ADD")


def createBoneGroup(o: bpy.types.Object, name: str, color_set="DEFAULT"):
    # create group
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode="POSE", toggle=False)
    bpy.ops.pose.group_add()
    # set name
    pose = o.pose
    g = pose.bone_groups.active
    g.name = name
    g.color_set = color_set
    return g


def createTexture(path: str) -> Tuple[bpy.types.Texture, bpy.types.Image]:
    texture = bpy.data.textures.new(os.path.basename(path), "IMAGE")
    texture.use_mipmap = True
    texture.use_interpolation = True
    texture.use_alpha = True
    try:
        image = bpy.data.images.load(path)
    except RuntimeError:
        if os.path.exists(path):
            print("fail to load. create fallback empty:", path)
        else:
            print("file not found:", path)
        image = bpy.data.images.new("Image", width=16, height=16)
    texture.image = image
    return texture, image


def addTexture(material, texture, enable=True, blend_type="MULTIPLY"):
    # search free slot
    index = None
    for i, slot in enumerate(material.texture_slots):
        if not slot:
            index = i
            break
    if index == None:
        return
    material.use_shadeless = True
    #
    slot = material.texture_slots.create(index)
    slot.texture = texture
    slot.texture_coords = "UV"
    slot.blend_type = blend_type
    slot.use_map_alpha = True
    slot.use = enable
    return index


def makeEditable(armature_object):
    # select only armature object and set edit mode
    bpy.context.view_layer.objects.active = armature_object
    bpy.ops.object.mode_set(mode="OBJECT", toggle=False)
    bpy.ops.object.mode_set(mode="EDIT", toggle=False)


def addIk(p_bone, armature_object, effector_name, chain, weight, iterations):
    constraint = p_bone.constraints.new("IK")
    constraint.chain_count = len(chain)
    constraint.target = armature_object
    constraint.subtarget = effector_name
    constraint.use_tail = False
    # constraint.influence=weight * 0.25
    constraint.iterations = iterations * 10


def addCopyRotation(pose_bone, target_object, target_bone, factor):
    c = pose_bone.constraints.new(type="COPY_ROTATION")
    c.target = target_object
    c.subtarget = target_bone.name
    c.influence = factor
    c.target_space = "LOCAL"
    c.owner_space = "LOCAL"


def convert_coord(pos, scale=1.0):
    """
    Left handed y-up to Right handed z-up
    """
    return (pos.x * scale, pos.z * scale, pos.y * scale)


def VtoV(v):
    return createVector(v.x, v.y, v.z)


def createVector(x, y, z):
    return mathutils.Vector([x, y, z])


def trim_by_utf8_21byte(src):
    len_list = [len(src[:i].encode("utf-8")) for i in range(1, len(src) + 1, 1)]
    max_length = 21
    letter_count = 0
    for str_len in len_list:
        if str_len > max_length:
            break
        letter_count += 1
    return src[:letter_count]


def get_object_name(fmt, index, name):
    """
    object名を作る。最大21バイト
    """
    # len_list=[len(name[:i].encode('utf-8')) for i in range(1, len(name)+1, 1)]
    # prefix=
    return trim_by_utf8_21byte(fmt.format(index) + name)
    """
    max_length=21-len(prefix)
    for str_len in len_list:
        if str_len>max_length:
            break
        letter_count+=1
    name=prefix+name[:letter_count]
    #print("%s(%d)" % (name, letter_count))
    return name
    """


def __import_joints(joints, rigidbodies) -> bpy.types.Collection:
    print("create joints")
    container = bpy.data.collections.new("Joints")
    layers = [
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    material = bpy.data.materials.new("joint")

    material.diffuse_color = (1, 0, 0)
    constraintMeshes = []
    for i, c in enumerate(joints):
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=8,
            ring_count=4,
            size=0.1,
            location=(c.position.x, c.position.z, c.position.y),
            layers=layers,
        )
        meshObject = bpy.context.active_object
        constraintMeshes.append(meshObject)
        mesh = meshObject.data
        mesh.materials.append(material)
        meshObject.name = get_object_name("j{0:02}:", i, c.name)
        # meshObject.draw_transparent=True
        # meshObject.draw_wire=True
        meshObject.draw_type = "SOLID"
        rot = c.rotation
        meshObject.rotation_euler = (-rot.x, -rot.z, -rot.y)

        meshObject[bl.CONSTRAINT_NAME] = c.name
        meshObject[bl.CONSTRAINT_A] = rigidbodies[c.rigidbody_index_a].name
        meshObject[bl.CONSTRAINT_B] = rigidbodies[c.rigidbody_index_b].name
        meshObject[bl.CONSTRAINT_POS_MIN] = VtoV(c.translation_limit_min)
        meshObject[bl.CONSTRAINT_POS_MAX] = VtoV(c.translation_limit_max)
        meshObject[bl.CONSTRAINT_ROT_MIN] = VtoV(c.rotation_limit_min)
        meshObject[bl.CONSTRAINT_ROT_MAX] = VtoV(c.rotation_limit_max)
        meshObject[bl.CONSTRAINT_SPRING_POS] = VtoV(c.spring_constant_translation)
        meshObject[bl.CONSTRAINT_SPRING_ROT] = VtoV(c.spring_constant_rotation)

    for meshObject in reversed(constraintMeshes):
        container.objects.link(meshObject)

    return container


def __importRigidBodies(rigidbodies, bones) -> bpy.types.Collection:
    print("create rigid bodies")

    container = bpy.data.collections.new("RigidBodies")
    layers = [
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    material = bpy.data.materials.new("rigidBody")
    rigidMeshes = []
    for i, rigid in enumerate(rigidbodies):
        if rigid.bone_index == -1:
            # no reference bone
            bone = bones[0]
        else:
            bone = bones[rigid.bone_index]
        pos = rigid.shape_position
        size = rigid.shape_size

        if rigid.shape_type == 0:
            bpy.ops.mesh.primitive_ico_sphere_add(
                location=(pos.x, pos.z, pos.y), layers=layers
            )
            bpy.ops.transform.resize(value=(size.x, size.x, size.x))
        elif rigid.shape_type == 1:
            bpy.ops.mesh.primitive_cube_add(
                location=(pos.x, pos.z, pos.y), layers=layers
            )
            bpy.ops.transform.resize(value=(size.x, size.z, size.y))
        elif rigid.shape_type == 2:
            bpy.ops.mesh.primitive_cylinder_add(
                location=(pos.x, pos.z, pos.y), layers=layers
            )
            bpy.ops.transform.resize(value=(size.x, size.x, size.y))
        else:
            assert False

        meshObject = bpy.context.active_object
        mesh = meshObject.data
        rigidMeshes.append(meshObject)
        mesh.materials.append(material)
        meshObject.name = get_object_name("r{0:02}:", i, rigid.name)
        # meshObject.draw_transparent=True
        # meshObject.draw_wire=True
        meshObject.draw_type = "WIRE"
        rot = rigid.shape_rotation
        meshObject.rotation_euler = (-rot.x, -rot.z, -rot.y)

        meshObject[bl.RIGID_NAME] = rigid.name
        meshObject[bl.RIGID_SHAPE_TYPE] = rigid.shape_type
        meshObject[bl.RIGID_PROCESS_TYPE] = rigid.mode
        meshObject[bl.RIGID_BONE_NAME] = bone.name
        meshObject[bl.RIGID_GROUP] = rigid.collision_group
        meshObject[bl.RIGID_INTERSECTION_GROUP] = rigid.no_collision_group
        meshObject[bl.RIGID_WEIGHT] = rigid.param.mass
        meshObject[bl.RIGID_LINEAR_DAMPING] = rigid.param.linear_damping
        meshObject[bl.RIGID_ANGULAR_DAMPING] = rigid.param.angular_damping
        meshObject[bl.RIGID_RESTITUTION] = rigid.param.restitution
        meshObject[bl.RIGID_FRICTION] = rigid.param.friction

    for meshObject in reversed(rigidMeshes):
        container.objects.link(meshObject)

    return container


def __create_a_material(m, name, textures_and_images):
    """
    materialを作成する

    :Params:
        m
            pymeshio.pmx.Material
        name
            material name
        textures_and_images
            list of (texture, image)
    """
    material = bpy.data.materials.new(name)
    # diffuse
    # material.diffuse_shader = "FRESNEL"
    # material.diffuse_color = [m.diffuse_color.r, m.diffuse_color.g, m.diffuse_color.b]
    # material.alpha = m.alpha
    # # specular
    # material.specular_shader = "TOON"
    # material.specular_color = [
    #     m.specular_color.r,
    #     m.specular_color.g,
    #     m.specular_color.b,
    # ]
    # material.specular_toon_size = m.specular_factor * 0.1
    # # ambient
    # material.mirror_color = [m.ambient_color.r, m.ambient_color.g, m.ambient_color.b]
    # # flag
    # material[bl.MATERIALFLAG_BOTHFACE] = m.hasFlag(pmx.MATERIALFLAG_BOTHFACE)
    # material[bl.MATERIALFLAG_GROUNDSHADOW] = m.hasFlag(pmx.MATERIALFLAG_GROUNDSHADOW)
    # material[bl.MATERIALFLAG_SELFSHADOWMAP] = m.hasFlag(pmx.MATERIALFLAG_SELFSHADOWMAP)
    # material[bl.MATERIALFLAG_SELFSHADOW] = m.hasFlag(pmx.MATERIALFLAG_SELFSHADOW)
    # material[bl.MATERIALFLAG_EDGE] = m.hasFlag(pmx.MATERIALFLAG_EDGE)
    # # edge_color
    # # edge_size
    # # other
    # material.preview_render_type = "FLAT"
    # material.use_transparency = True
    # # texture
    # if m.texture_index != -1:
    #     texture = textures_and_images[m.texture_index][0]
    #     addTexture(material, texture)
    # # toon texture
    # if m.toon_sharing_flag == 1:
    #     material[bl.MATERIAL_SHAREDTOON] = m.toon_texture_index
    # else:
    #     if m.toon_texture_index != -1:
    #         toon_texture = textures_and_images[m.toon_texture_index][0]
    #         toon_texture[bl.TEXTURE_TYPE] = "TOON"
    #         addTexture(material, toon_texture)
    # # sphere texture
    # if m.sphere_mode == pmx.MATERIALSPHERE_NONE:
    #     material[bl.MATERIAL_SPHERE_MODE] = pmx.MATERIALSPHERE_NONE
    # elif m.sphere_mode == pmx.MATERIALSPHERE_SPH:
    #     # SPH
    #     if m.sphere_texture_index == -1:
    #         material[bl.MATERIAL_SPHERE_MODE] = pmx.MATERIALSPHERE_NONE
    #     else:
    #         sph_texture = textures_and_images[m.sphere_texture_index][0]
    #         sph_texture[bl.TEXTURE_TYPE] = "SPH"
    #         addTexture(material, sph_texture)
    #         material[bl.MATERIAL_SPHERE_MODE] = m.sphere_mode
    # elif m.sphere_mode == pmx.MATERIALSPHERE_SPA:
    #     # SPA
    #     if m.sphere_texture_index == -1:
    #         material[bl.MATERIAL_SPHERE_MODE] = pmx.MATERIALSPHERE_NONE
    #     else:
    #         spa_texture = textures_and_images[m.sphere_texture_index][0]
    #         spa_texture[bl.TEXTURE_TYPE] = "SPA"
    #         addTexture(material, spa_texture, True, "ADD")

    #         material[bl.MATERIAL_SPHERE_MODE] = m.sphere_mode
    # else:
    #     print("unknown sphere mode:", m.sphere_mode)
    return material


def __create_armature(
    collection: bpy.types.Collection, name: str, bones, display_slots, scale: float
) -> bpy.types.Object:
    """
    :Params:
        bones
            list of pymeshio.pmx.Bone
    """
    armature = bpy.data.armatures.new("PmxArmature")
    armature_object = bpy.data.objects.new(name, armature)
    collection.objects.link(armature_object)
    armature_object.show_in_front = True
    armature.display_type = "STICK"

    # numbering
    for i, b in enumerate(bones):
        b.index = i

    # create bones
    makeEditable(armature_object)

    def create_bone(b):
        bone = armature.edit_bones.new(b.name)
        bone[bl.BONE_ENGLISH_NAME] = b.english_name
        # bone position
        bone.head = createVector(*convert_coord(b.position))
        if b.getConnectionFlag():
            # dummy tail
            bone.tail = bone.head + createVector(0, 1, 0)
        else:
            # offset tail
            bone.tail = bone.head + createVector(*convert_coord(b.tail_position))
            if bone.tail == bone.head:
                # 捻りボーン
                bone.tail = bone.head + createVector(0, 0.01, 0)
            pass
        if not b.getVisibleFlag():
            # dummy tail
            bone.tail = bone.head + createVector(0, 0.01, 0)

        bone.head *= scale
        bone.tail *= scale

        return bone

    bl_bones = [create_bone(b) for b in bones]

    # build skeleton
    used_bone_name = set()
    for b, bone in zip(bones, bl_bones):
        if b.name != bone.name:
            if b.name in used_bone_name:
                print("duplicated bone name:[%s][%s]" % (b.name, bone.name))
            else:
                print("invalid name:[%s][%s]" % (b.name, bone.name))
        used_bone_name.add(b.name)
        if b.parent_index != -1:
            # set parent
            parent_bone = bl_bones[b.parent_index]
            bone.parent = parent_bone

        if b.getConnectionFlag() and b.tail_index != -1:
            assert b.tail_index != 0
            # set tail position
            tail_bone = bl_bones[b.tail_index]
            bone.tail = tail_bone.head
            # connect with child
            tail_b = bones[b.tail_index]
            if bones[tail_b.parent_index] == b:
                # connect with tail
                tail_bone.use_connect = True

        if bone.head == bone.tail:
            # no size bone...
            print(bone)
            bone.tail.z -= 0.00001

    # pose bone construction
    bpy.ops.object.mode_set(mode="OBJECT", toggle=False)
    pose = armature_object.pose
    for b in bones:
        p_bone = pose.bones[b.name]
        if b.hasFlag(pmx.BONEFLAG_IS_IK):
            # create ik constraint
            ik = b.ik
            assert len(ik.link) < 16
            ik_p_bone = pose.bones[bones[ik.target_index].name]
            assert ik_p_bone
            addIk(ik_p_bone, armature_object, b.name, ik.link, ik.limit_radian, ik.loop)
            armature.bones[b.name][bl.IK_UNITRADIAN] = ik.limit_radian
            for chain in ik.link:
                if chain.limit_angle:
                    ik_p_bone = pose.bones[bones[chain.bone_index].name]
                    # IK limit
                    # x
                    if chain.limit_min.x == 0 and chain.limit_max.x == 0:
                        ik_p_bone.lock_ik_x = True
                    else:
                        ik_p_bone.use_ik_limit_x = True
                        # left handed to right handed ?
                        ik_p_bone.ik_min_x = -chain.limit_max.x
                        ik_p_bone.ik_max_x = -chain.limit_min.x

                    # y
                    if chain.limit_min.y == 0 and chain.limit_max.y == 0:
                        ik_p_bone.lock_ik_y = True
                    else:
                        ik_p_bone.use_ik_limit_y = True
                        ik_p_bone.ik_min_y = chain.limit_min.y
                        ik_p_bone.ik_max_y = chain.limit_max.y

                    # z
                    if chain.limit_min.z == 0 and chain.limit_max.z == 0:
                        ik_p_bone.lock_ik_z = True
                    else:
                        ik_p_bone.use_ik_limit_z = True
                        ik_p_bone.ik_min_z = chain.limit_min.z
                        ik_p_bone.ik_max_z = chain.limit_max.z

        if b.hasFlag(pmx.BONEFLAG_IS_EXTERNAL_ROTATION):
            constraint_p_bone = pose.bones[bones[b.effect_index].name]
            addCopyRotation(p_bone, armature_object, constraint_p_bone, b.effect_factor)

        if b.hasFlag(pmx.BONEFLAG_HAS_FIXED_AXIS):
            c = p_bone.constraints.new(type="LIMIT_ROTATION")
            c.owner_space = "LOCAL"

        if b.parent_index != -1:
            parent_b = bones[b.parent_index]
            if (
                parent_b.hasFlag(pmx.BONEFLAG_TAILPOS_IS_BONE)
                and parent_b.tail_index == b.index
            ):
                # 移動制限を尻尾位置の接続フラグに流用する
                c = p_bone.constraints.new(type="LIMIT_LOCATION")
                c.owner_space = "LOCAL"
            else:
                parent_parent_b = bones[parent_b.parent_index]
                if (
                    parent_parent_b.hasFlag(pmx.BONEFLAG_TAILPOS_IS_BONE)
                    and parent_parent_b.tail_index == b.index
                ):
                    # 移動制限を尻尾位置の接続フラグに流用する
                    c = p_bone.constraints.new(type="LIMIT_LOCATION")
                    c.owner_space = "LOCAL"

        if not b.hasFlag(pmx.BONEFLAG_CAN_TRANSLATE):
            # translatation lock
            p_bone.lock_location = (True, True, True)

    makeEditable(armature_object)

    # create bone group
    bpy.ops.object.mode_set(mode="OBJECT", toggle=False)
    pose = armature_object.pose
    for i, ds in enumerate(display_slots):
        # print(ds)
        g = createBoneGroup(armature_object, ds.name, "THEME%02d" % (i + 1))
        for t, index in ds.references:
            if t == 0:
                name = bones[index].name
                try:
                    pose.bones[name].bone_group = g
                except KeyError as e:
                    print("pose %s is not found" % name)

    bpy.ops.object.mode_set(mode="OBJECT", toggle=False)

    # fix flag
    boneNameMap = {}
    for b in bones:
        boneNameMap[b.name] = b
    for b in armature.bones.values():
        if not boneNameMap[b.name].hasFlag(pmx.BONEFLAG_IS_VISIBLE):
            b.hide = True
        if not boneNameMap[b.name].hasFlag(pmx.BONEFLAG_TAILPOS_IS_BONE):
            b[bl.BONE_USE_TAILOFFSET] = True

    return armature_object


def import_pmx_model(
    parent_collection: bpy.types.Collection,
    filepath: str,
    model: pmx.Model,
    import_mesh: bool,
    import_physics: bool,
    scale: float,
    **kwargs,
) -> bool:
    if not model:
        print("fail to load %s" % filepath)
        return False
    # print(model)

    model_name = model.name
    if len(model_name) == 0:
        model_name = model.english_name
        if len(model_name) == 0:
            model_name = os.path.basename(filepath)
    collection = bpy.data.collections.new(model_name)
    parent_collection.children.link(collection)

    armature_object = __create_armature(
        collection, model_name, model.bones, model.display_slots, scale
    )
    armature_object[bl.MMD_MB_NAME] = model.name
    armature_object[bl.MMD_ENGLISH_NAME] = model.english_name
    armature_object[bl.MMD_MB_COMMENT] = model.comment
    armature_object[bl.MMD_ENGLISH_COMMENT] = model.english_comment

    if import_mesh:
        # テクスチャを作る
        texture_dir = os.path.dirname(filepath)
        # print(model.textures)
        textures_and_images = [
            createTexture(os.path.join(texture_dir, t)) for t in model.textures
        ]
        # print(textures_and_images)

        ####################
        # mesh object
        ####################
        mesh = bpy.data.meshes.new("Mesh")
        mesh_object = None
        i = 0
        while not mesh_object:
            try:
                mesh_object = bpy.data.objects.new(f"mesh.{i:03}", mesh)
                break
            except:
                i += 1
        collection.objects.link(mesh_object)

        # activate object
        bpy.ops.object.select_all(action="DESELECT")

        mesh_object.select_set(True)
        bpy.context.view_layer.objects.active = mesh_object

        ####################
        # vertices & faces
        ####################
        # 頂点配列。(Left handed y-up) to (Right handed z-up)
        vertices = [
            convert_coord(pos, scale) for pos in (v.position for v in model.vertices)
        ]
        # normals = [convert_coord(nom) for nom in (v.normal for v in model.vertices)]
        # flip
        faces = [
            (model.indices[i + 2], model.indices[i + 1], model.indices[i])
            for i in range(0, len(model.indices), 3)
        ]
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        assert len(model.vertices) == len(mesh.vertices)
        mesh.uv_layers.new(name=UV_NAME)

        ####################
        # material
        ####################
        index_gen = (i for i in model.indices)
        face_gen = ((i, pl) for i, pl in enumerate(mesh.polygons))
        uv_gen = ((i, uv) for i, uv in enumerate(mesh.uv_layers[UV_NAME].data))
        for i, m in enumerate(model.materials):
            name = get_object_name("{0:02}:", i, m.name)
            material = __create_a_material(m, name, textures_and_images)
            mesh.materials.append(material)

            def get_or_none(
                i: int,
            ) -> Optional[Tuple[bpy.types.Texture, bpy.types.Image]]:
                try:
                    return textures_and_images[i]
                except:
                    return None

            # texture image
            image = (
                get_or_none(m.texture_index)
                if m.texture_index in textures_and_images
                else None
            )

            # face params
            for _ in range(0, m.vertex_count, 3):
                face_index, face = next(face_gen)
                # assign material
                face.material_index = i
                # assign uv
                i0 = next(index_gen)
                i1 = next(index_gen)
                i2 = next(index_gen)
                uv0 = model.vertices[i0].uv
                uv1 = model.vertices[i1].uv
                uv2 = model.vertices[i2].uv
                _, uv_face = next(uv_gen)
                uv_face.uv = (uv2.x, 1.0 - uv2.y)
                _, uv_face = next(uv_gen)
                uv_face.uv = (uv1.x, 1.0 - uv1.y)
                _, uv_face = next(uv_gen)
                uv_face.uv = (uv0.x, 1.0 - uv0.y)
                # print(uv_face.uv)
                if image:
                    uv_face.image = image
                    uv_face.use_image = True

                # set smooth
                face.use_smooth = True
                # mesh.vertices[i0].normal = normals[i0]

        # fix mesh
        mesh.update()

        ####################
        # armature
        ####################
        # armature modifirer
        mod = mesh_object.modifiers.new("Modifier", "ARMATURE")
        mod.object = armature_object
        mod.use_bone_envelopes = False
        for i, (v, mvert) in enumerate(zip(model.vertices, mesh.vertices)):
            if isinstance(v.deform, pmx.Bdef1):
                assignVertexGroup(
                    mesh_object, model.bones[v.deform.index0].name, i, 1.0
                )
            elif isinstance(v.deform, pmx.Bdef2):
                assignVertexGroup(
                    mesh_object,
                    model.bones[v.deform.index0].name,
                    i,
                    v.deform.weight0,
                )
                assignVertexGroup(
                    mesh_object,
                    model.bones[v.deform.index1].name,
                    i,
                    1.0 - v.deform.weight0,
                )
            elif isinstance(v.deform, pmx.Bdef4):
                assignVertexGroup(
                    mesh_object,
                    model.bones[v.deform.index0].name,
                    i,
                    v.deform.weight0,
                )
                assignVertexGroup(
                    mesh_object,
                    model.bones[v.deform.index1].name,
                    i,
                    v.deform.weight1,
                )
                assignVertexGroup(
                    mesh_object,
                    model.bones[v.deform.index2].name,
                    i,
                    v.deform.weight2,
                )
                assignVertexGroup(
                    mesh_object,
                    model.bones[v.deform.index3].name,
                    i,
                    v.deform.weight3,
                )
            elif isinstance(v.deform, pmx.Sdef):
                # fail safe
                assignVertexGroup(
                    mesh_object,
                    model.bones[v.deform.index0].name,
                    i,
                    v.deform.weight0,
                )
                assignVertexGroup(
                    mesh_object,
                    model.bones[v.deform.index1].name,
                    i,
                    1.0 - v.deform.weight0,
                )
            else:
                raise Exception("unknown deform: %s" % v.deform)

        ####################
        # shape keys
        ####################
        # if len(model.morphs) > 0:
        #     # set shape_key pin
        #     mesh_object.show_only_shape_key = True
        #     # create base key
        #     mesh_object.vertex_groups.new(bl.MMD_SHAPE_GROUP_NAME)
        #     # assign all vertext to group
        #     for i, v in enumerate(mesh.vertices):
        #         assignVertexGroup(mesh_object, bl.MMD_SHAPE_GROUP_NAME, i, 0)
        #     # create base key
        #     baseShapeBlock = mesh_object.shape_key_add(bl.BASE_SHAPE_NAME)
        #     mesh.update()

        #     # each morph
        #     for m in model.morphs:
        #         new_shape_key = mesh_object.shape_key_add(m.name)
        #         for o in m.offsets:
        #             if isinstance(o, pmx.VertexMorphOffset):
        #                 # vertex morph
        #                 new_shape_key.data[o.vertex_index].co = mesh.vertices[
        #                     o.vertex_index
        #                 ].co + createVector(*convert_coord(o.position_offset))
        #             else:
        #                 print("unknown morph type: %s. drop" % o)
        #                 # raise Exception("unknown morph type: %s" % o)
        #                 break

        #     # select base shape
        #     mesh_object.active_shape_key_index = 0

    if import_physics:
        # import rigid bodies
        rigidbody_collection = __importRigidBodies(model.rigidbodies, model.bones)
        if rigidbody_collection:
            collection.objects.link(rigidbody_collection)

        # import joints
        joint_collection = __import_joints(model.joints, model.rigidbodies)
        if joint_collection:
            collection.children.link(joint_collection)

    bpy.context.view_layer.objects.active = armature_object

    return True


def _execute(
    collection: bpy.types.Collection, filepath: str, **kwargs
) -> Optional[bpy.types.Collection]:
    if filepath.lower().endswith(".pmd"):
        from .pymeshio.pmd import reader

        pmd_model = reader.read_from_file(filepath)
        if not pmd_model:
            return

        print("convert pmd to pmx...")
        from .pymeshio import converter

        return import_pmx_model(
            collection, filepath, converter.pmd_to_pmx(pmd_model), **kwargs
        )

    elif filepath.lower().endswith(".pmx"):
        from .pymeshio.pmx import reader

        pmx_model = reader.read_from_file(filepath)
        if not pmx_model:
            return

        return import_pmx_model(collection, filepath, pmx_model, **kwargs)

    else:
        print("unknown file type: ", filepath)
        return


class ImportPmx(bpy.types.Operator, bpy_extras.io_utils.ImportHelper):
    """Import from PMX Format(.pmx)(.pmd)"""

    bl_idname = "import_scene.mmd_pmx_pmd"
    bl_label = "Import PMX/PMD"
    bl_options = {"UNDO"}
    filename_ext = ".pmx;.pmd"
    filter_glob = bpy.props.StringProperty(default="*.pmx;*.pmd", options={"HIDDEN"})

    import_mesh: bpy.props.BoolProperty(  # type: ignore
        name="import mesh", description="import polygon mesh", default=True
    )

    import_physics: bpy.props.BoolProperty(  # type: ignore
        name="import physics objects",
        description="import rigid body and constraints",
        default=False,
    )

    scale: bpy.props.FloatProperty(  # type: ignore
        name="position scaling",
        description="default is to meter",
        default=1.63 / 20,
    )

    def execute(self, context):
        try:
            _execute(
                context.scene.collection, **self.as_keywords(ignore=("filter_glob",))
            )
            return {"FINISHED"}
        except Exception as ex:
            print(ex)
            return {"CANCELLED"}


def menu_func(self, context):
    self.layout.operator(
        ImportPmx.bl_idname, text="MikuMikuDance model (.pmx)(.pmd)", icon="PLUGIN"
    )
