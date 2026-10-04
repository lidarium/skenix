# Architectural Modeling Plugin

Welcome to our architectural modeling plugin! This tool is specifically designed to provide a comfortable and intuitive transition for architects coming from familiar direct 3D modeling environments.

## Features

- **Intuitive Workflow**: Our plugin closely mimics the simple and direct modeling approach that architects love, offering familiar drawing and editing tools for rapid conceptualization and design.
- **Easy Mesh Manipulation**: Push, pull, and shape geometries with ease. Our easy mesh manipulation tools allow you to quickly build and iterate on architectural forms without a steep learning curve.
- **Architect-Focused**: Built specifically with the needs of architects in mind, streamlining the process from rough sketch to detailed architectural model.

## Origin of the Name

Skenix (pronounced SKEE-nix / ˈskiːnɪks/) derives from the ancient Greek word skēnē (σκηνή, skay-NAY)—the root of scene—which originally referred to a shelter or shaded structure ("that which casts shade"), before evolving into the architectural backdrop and stage façade of classical theater. It represents the space where perspective, form, and spatial staging begin.

## Acknowledgments

This add-on is being developed by merging the mathematical concepts and core workflows from two pioneering add-ons designed to replicate familiar Push/Pull tools from direct 3D modeling environments in Blender.

We would like to credit the original authors:

*   **[Destructive Extrude](https://github.com/Darcvizer/Destructive-Extrude) by Vladislav Kindushov (Darcvizer)**
    This repository provided the Constructive Solid Geometry (CSG) engine. It introduced the concept of dynamically generating a 3D block from a face selection and using an EXACT Boolean solver in the background to cleanly carve holes through architectural geometry.

*   **[Extrude and Reshape](https://github.com/Mano-Wii/Addon-Extrude-and-Reshape) by Germano Cavalcante (Mano-Wii)**
    This repository provided the foundation for the native topological push/pull approach. Germano Cavalcante’s work on this specific tool was so highly regarded that the Blender Foundation officially hired him to rewrite it into Blender's C++ source code. His add-on evolved directly into the native Extrude Manifold tool that our script uses for outward volume generation.
