# CoCoEPROMpak

## 📖 The Book

This project is **Chapter 7, "CoCo EPROM Pak"**, in a book:

**Chips, Code, and Cartridges: Turn Curiosity into Creation with 13 Hands-On Projects, from 8-bit Classics to FPGAs**

It walks through thirteen of my own hardware and software projects, from 8-bit classics to FPGAs, for beginners and curious makers. Each chapter explains how one project works and how to build it, with colour diagrams and real code from its repository.

### 👉 [Get the book on Amazon](https://link.amazon/B013Yaq9y)

<sub>As an Amazon Associate, the author earns from qualifying purchases. Buying through this link
supports these projects at no extra cost to you.</sub>

## Writing the ROM from the CoCo

The AT28C256 version can be programmed while it sits in the CoCo, with no programmer. The writer, the PC
tool that prepares ROM images and its tests are in [`Software/EEWRITE`](Software/EEWRITE). It needs the
/OE modification described there and in the book.
