from dcc_mcp_core.skill import run_main

from dcc_mcp_krita.skill_tools import bridge_main

main = bridge_main("krita.open_document", "Krita document opened.")

if __name__ == "__main__":
    run_main(main)
