from dcc_mcp_core.skill import run_main

from dcc_mcp_krita.skill_tools import bridge_main

main = bridge_main("krita.create_paint_layer", "Krita paint layer created.")

if __name__ == "__main__":
    run_main(main)
