from dcc_mcp_core.skill import run_main

from dcc_mcp_krita.skill_tools import bridge_main

main = bridge_main("krita.export_document", "Krita document exported.")

if __name__ == "__main__":
    run_main(main)
