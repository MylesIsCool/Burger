#!/usr/bin/env python
# -*- coding: utf8 -*-
"""
Copyright (c) 2011 Tyler Kenendy <tk@tkte.ch>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from .topping import Topping

from jawa.constants import *
from jawa.cf import ClassFile

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

class EntityTopping(Topping):
    """Gets most entity types."""

    PROVIDES = [
        "entities.entity"
    ]

    DEPENDS = [
        "identify.entity.list"
    ]

    @staticmethod
    def act(aggregate, jar, verbose=False):
        superclass = aggregate["classes"]["entity.list"]
        cf = ClassFile(StringIO(jar.read(superclass + ".class")))

        # Find the static constructor
        entities = aggregate.setdefault("entities", {})
        entity = entities.setdefault("entity", {})
        alias = entities.setdefault("alias", {})
        tmp = {}

        minecart_info = entities.setdefault("minecart_info", {})

        def load_minecart_enum(classname):
            """Stores data about the minecart enum in aggregate"""
            minecart_info["class"] = classname

            minecart_types = minecart_info.setdefault("types", {})
            minecart_types_by_field = minecart_info.setdefault("types_by_field", {})

            minecart_cf = ClassFile(StringIO(jar.read(classname + ".class")))
            init_method = minecart_cf.methods.find_one("<clinit>")

            already_has_minecart_name = False
            for ins in init_method.code.disassemble():
                if ins.mnemonic == "new":
                    const = minecart_cf.constants.get(ins.operands[0].value)
                    minecart_class = const.name.value
                elif ins.mnemonic == "ldc":
                    const = minecart_cf.constants.get(ins.operands[0].value)
                    if isinstance(const, ConstantString):
                        if already_has_minecart_name:
                            minecart_type = const.string.value
                        else:
                            already_has_minecart_name = True
                            minecart_name = const.string.value
                elif ins.mnemonic == "putstatic":
                    const = minecart_cf.constants.get(ins.operands[0].value)
                    if const.name_and_type.descriptor.value != "L" + classname + ";":
                        # Other parts of the enum initializer (values array) that we don't care about
                        continue

                    minecart_field = const.name_and_type.name.value

                    minecart_types[minecart_name] = {
                        "class": minecart_class,
                        "field": minecart_field,
                        "name": minecart_name,
                        "entitytype": minecart_type
                    }
                    minecart_types_by_field[minecart_field] = minecart_name

                    already_has_minecart_name = False

        # Detect whether post-1.11 logic should be used
        is_1point11 = False
        for c in cf.constants.find(ConstantString):
            # Lowercase 1.11 naming in a special constant
            if c.string.value == "lightning_bolt":
                is_1point11 = True
                break

        if is_1point11:
            # 1.11 logic
            if verbose:
                print "Using 1.11 entity format"

            method = cf.methods.find_one(args='', returns="V", f=lambda m: m.access_flags.acc_public and m.access_flags.acc_static)

            stack = []
            for ins in method.code.disassemble():
                if ins.mnemonic in ("ldc", "ldc_w"):
                    const = cf.constants.get(ins.operands[0].value)
                    if isinstance(const, ConstantClass):
                        stack.append(const.name.value)
                    elif isinstance(const, ConstantString):
                        stack.append(const.string.value)
                    else:
                        stack.append(const.value)
                elif ins.mnemonic in ("bipush", "sipush"):
                    stack.append(ins.operands[0].value)
                elif ins.opcode <= 8 and ins.opcode >= 2: # iconst
                    stack.append(ins.opcode - 3)
                elif ins.mnemonic == "getstatic":
                    # Minecarts use an enum for their data - assume that this is that enum
                    const = cf.constants.get(ins.operands[0].value)
                    if not "types_by_field" in minecart_info:
                        load_minecart_enum(const.class_.name.value)
                    # This technically happens when invokevirtual is called, but do it like this for simplicity
                    minecart_name = minecart_info["types_by_field"][const.name_and_type.name.value]
                    stack.append(minecart_info["types"][minecart_name]["entitytype"])
                elif ins.mnemonic == "invokestatic":
                    if len(stack) == 4:
                        # Initial registration
                        name = stack[1]

                        entity[name] = {
                            "id": stack[0],
                            "name": name,
                            "class": stack[2],
                            "old_name": stack[3]
                        }
                    elif len(stack) == 3:
                        # Spawn egg registration
                        name = stack[0]
                        if name in entity:
                            entity[name]["egg_primary"] = stack[1]
                            entity[name]["egg_secondary"] = stack[2]
                        else:
                            print "Missing entity during egg registration:", name
                    stack = []
        else:
            # 1.10 logic
            if verbose:
                print "Using 1.10 entity format"

            method = cf.methods.find_one("<clinit>")
            mode = "starting"

            stack = []
            for ins in method.code.disassemble():
                if mode == "starting":
                    # We don't care about the logger setup stuff at the beginning;
                    # wait until an entity definition starts.
                    if ins.mnemonic in ("ldc", "ldc_w"):
                        mode = "entities"
                # elif is not used here because we need to handle modes changing
                if mode != "starting":
                    if ins.mnemonic in ("ldc", "ldc_w"):
                        const = cf.constants.get(ins.operands[0].value)
                        if isinstance(const, ConstantClass):
                            stack.append(const.name.value)
                        elif isinstance(const, ConstantString):
                            stack.append(const.string.value)
                        else:
                            stack.append(const.value)
                    elif ins.mnemonic in ("bipush", "sipush"):
                        stack.append(ins.operands[0].value)
                    elif ins.opcode <= 8 and ins.opcode >= 2: # iconst
                        stack.append(ins.opcode - 3)
                    elif ins.mnemonic == "new":
                        # Entity aliases (for lack of a better term) start with 'new's.
                        # Switch modes (this operation will be processed there)
                        mode = "aliases"
                        const = cf.constants.get(ins.operands[0].value)
                        stack.append(const.name.value)
                    elif ins.mnemonic == "getstatic":
                        # Minecarts use an enum for their data - assume that this is that enum
                        const = cf.constants.get(ins.operands[0].value)
                        if not "types_by_field" in minecart_info:
                            load_minecart_enum(const.class_.name.value)
                        # This technically happens when invokevirtual is called, but do it like this for simplicity
                        minecart_name = minecart_info["types_by_field"][const.name_and_type.name.value]
                        stack.append(minecart_info["types"][minecart_name]["entitytype"])
                    elif ins.mnemonic == "invokestatic":  # invokestatic
                        if mode == "entities":
                            tmp["class"] = stack[0]
                            tmp["name"] = stack[1]
                            tmp["id"] = stack[2]
                            if (len(stack) >= 5):
                                tmp["egg_primary"] = stack[3]
                                tmp["egg_secondary"] = stack[4]
                            entity[tmp["name"]] = tmp
                        elif mode == "aliases":
                            tmp["entity"] = stack[0]
                            tmp["name"] = stack[1]
                            if (len(stack) >= 5):
                                tmp["egg_primary"] = stack[2]
                                tmp["egg_secondary"] = stack[3]
                            tmp["class"] = stack[-1] # last item, made by new.
                            alias[tmp["name"]] = tmp

                        tmp = {}
                        stack = []

        for e in entity.itervalues():
            cf = ClassFile(StringIO(jar.read(e["class"] + ".class")))
            size = EntityTopping.size(cf)
            if size:
                e["width"], e["height"], texture = size
                if texture:
                    e["texture"] = texture

        entities["info"] = {
            "entity_count": len(entity)
        }

    @staticmethod
    def size(cf):
        method = cf.methods.find_one("<init>")
        if method is None:
            return

        stage = 0
        tmp = []
        texture = None
        for ins in method.code.disassemble():
            if ins.mnemonic == "aload_0" and stage == 0:
                stage = 1
            elif ins.mnemonic in ("ldc", "ldc_w"):
                const = cf.constants.get(ins.operands[0].value)
                if isinstance(const, ConstantFloat) and stage in (1, 2):
                    tmp.append(round(const.value, 2))
                    stage += 1
                else:
                    stage = 0
                    tmp = []
                    if isinstance(const, ConstantString):
                        texture = const.string.value
            elif ins.mnemonic == "invokevirtual" and stage == 3:
                return tmp + [texture]
                break
            else:
                stage = 0
                tmp = []
