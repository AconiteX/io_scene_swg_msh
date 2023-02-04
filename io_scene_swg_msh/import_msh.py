# MIT License
#
# Copyright (c) 2022 Nick Rafalski
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import base64, os, bpy, time, datetime
import bmesh

from bpy_extras.io_utils import unpack_list
from bpy_extras.image_utils import load_image
from bpy_extras.wm_utils.progress_report import ProgressReport
from bpy_extras.object_utils import AddObjectHelper, object_data_add

from . import vertex_buffer_format
from . import swg_types

def load_new(context,
             filepath,
             *,     
             global_matrix=None,
             flip_uv_vertical=False,
             remove_duplicate_verts=True,
             ):
    print(f'Importing msh: {filepath} Flip UV: {flip_uv_vertical}')
    
    msh = swg_types.SWGMesh(filepath)
    if not msh.load():
        return {'ERROR'}
    
        
    name=os.path.basename(filepath).rsplit( ".", 1 )[ 0 ]
    mesh = bpy.data.meshes.new(name=f'{name}-mesh')
    obj = bpy.data.objects.new(name, mesh)
    context.collection.objects.link(obj)

    faces_by_material = {}
    materials_by_face_index = []
    normals=[]
    verts = []    
    face_uvs = []

    highest_vert_ind=0
    for index, sps in enumerate(msh.spss):
        faces_by_material[index] = []
        mat_name = sps.stripped_shader_name()
        material = None
        for mat in bpy.data.materials:
            if mat.name == mat_name:
                material = mat
        if material == None:
            material = bpy.data.materials.new(sps.stripped_shader_name())    
            material["Shader"] = sps.shader    
            material["UVSets"] =  sps.getNumUVSets()
            material["DOT3"] = sps.hasDOT3()

        mesh.materials.append(material) 
        uvs = []
        num_uv_sets = 0
        for ind, vert in enumerate(sps.verts):
            verts.append((-vert.pos.x, vert.pos.y, vert.pos.z))
            #normals.append((-vert.normal.x,vert.normal.y, vert.normal.z))

            num_uv_sets = len(vert.texs)
            for i in range(0, num_uv_sets):
                if (len(uvs) - 1) < i:
                    uvs.append([])
                if flip_uv_vertical:
                    vert.texs[i][1] = (1.0 - vert.texs[i][1])
                uvs[i].append(vert.texs[i])

            #print("Added Vert: %d : Pos: %s Normal: %s UV: %s" % (i, str(vert.pos), str(vert.normal), str(vert.texs)))

        for tri in sps.tris:
            p3 = tri.p3 + highest_vert_ind
            p2 = tri.p2 + highest_vert_ind
            p1 = tri.p1 + highest_vert_ind
            faces_by_material[index].append((p3, p2, p1))
            p3n = sps.verts[tri.p3].normal
            p2n = sps.verts[tri.p2].normal
            p1n = sps.verts[tri.p1].normal
            normals.append([-p3n.x, p3n.y, p3n.z])
            normals.append([-p2n.x, p2n.y, p2n.z])
            normals.append([-p1n.x, p1n.y, p1n.z])
            for i in range(0, len(uvs)):
                if (len(face_uvs) - 1) < i:
                    face_uvs.append([])
                face_uvs[i] += [
                    uvs[i][tri.p3][0], uvs[i][tri.p3][1],
                    uvs[i][tri.p2][0], uvs[i][tri.p2][1],
                    uvs[i][tri.p1][0], uvs[i][tri.p1][1],
                ]
            materials_by_face_index.append(index)
        highest_vert_ind += len(sps.verts)
        
    mesh.from_pydata(verts, [], sum(faces_by_material.values(), []))   

    # for id, face_list in faces_by_material.items():
    #     print(f"Faces by material: {id}: {len(face_list)}")

    #print(f"Doing material assignment ...")
    starttime=time.time()
    for flist in mesh.polygons:
        flist.material_index = materials_by_face_index[flist.index]
    #print(f"Done in: " + str(datetime.timedelta(seconds=(time.time()-starttime))))

    #print(f"Applying normals ...")
    mesh.use_auto_smooth = True
    mesh.normals_split_custom_set(normals)
    #print(f"Transforming ...")
    mesh.transform(global_matrix)      

    #print(f"Making UV maps ...")
    # Create a new UVMap for each uv set
    for i in range(0, len(face_uvs)):
        uv_layer = mesh.uv_layers.new(name=f'UVMap-{str(i)}')
        uv_layer.data.foreach_set("uv", face_uvs[i])

    if remove_duplicate_verts:
        #print(f"Removing duplicate verts ...")
        bm = bmesh.new()
        bm.from_mesh(mesh)
        before = len(mesh.vertices)
        removed = bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
        bm.to_mesh(mesh)        
        after = len(mesh.vertices)            
        print(f"SPS {index}: Removed: {before - after} verts")
        bm.free() 
        #print(f"Done!")

    mesh.update() 
    mesh.validate()

    for hpnts in msh.hardpoints:
        hpntadded = bpy.data.objects.new(name=hpnts[12], object_data=None)
        hpntadded.matrix_world = [
            [hpnts[0], hpnts[8], hpnts[4], 0.0],
            [hpnts[1], hpnts[9], hpnts[5], 0.0],
            [hpnts[2], hpnts[10], hpnts[6], 0.0],
            [hpnts[3], hpnts[11], hpnts[7], 0.0],
        ]
        hpntadded.empty_display_type = "ARROWS"
        hpntadded.empty_display_size = 0.1 #small display
        hpntadded.parent = obj
        bpy.context.collection.objects.link(hpntadded)

    obj["Collision"] = base64.b64encode(msh.collision).decode('ASCII')
    obj["Floor"] = msh.floor
    print(f"Success!")
            
    return {'FINISHED'}