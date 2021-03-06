import subprocess
import os.path
import os
import pathlib
import sys
import argparse
import webbrowser

from pbpy import pblog
from pbpy import pbhub
from pbpy import pbtools
from pbpy import pbunreal
from pbpy import pbgit
from pbpy import pbconfig
from pbpy import pbpy_version
from pbpy import pbdispatch
from pbpy import pbuac

import pbsync_version

default_config_name = "PBSync.xml"


def config_handler(config_var, config_parser_func):
    if not pbconfig.generate_config(config_var, config_parser_func):
        # Logger is not initialized yet, so use print instead
        print(f"{str(config_var)} config file is not valid or not found. Please check the integrity of the file")
        sys.exit(1)


def sync_handler(sync_val: str, repository_val=None, requested_bundle_name=None):

    sync_val = sync_val.lower()

    if sync_val == "all" or sync_val == "force":
        # Firstly, check our remote connection before doing anything
        remote_state, remote_url = pbgit.check_remote_connection()
        if not remote_state:
            pbtools.error_state(
                f"Remote connection was not successful. Please verify that you have a valid git remote URL & internet connection. Current git remote URL: {remote_url}")
        else:
            pblog.info("Remote connection is up")

        pblog.info("------------------")

        pblog.info(f"Executing {sync_val} sync command")
        pblog.info(f"PBpy Library Version: {pbpy_version.ver}")
        pblog.info(f"PBSync Program Version: {pbsync_version.ver}")

        pblog.info("------------------")

        detected_git_version = pbgit.get_git_version()
        needs_git_update = False
        if detected_git_version == pbconfig.get('supported_git_version'):
            pblog.info(f"Current Git version: {detected_git_version}")
        else:
            pblog.error("Git is not updated to the supported version in your system")
            pblog.error(f"Supported Git Version: {pbconfig.get('supported_git_version')}")
            pblog.error(f"Current Git Version: {detected_git_version}")
            pblog.error("Please install the supported Git version from https://github.com/microsoft/git/releases")
            pblog.error("Visit https://github.com/ProjectBorealisTeam/pb/wiki/Prerequisites for installation instructions")
            if os.name == "nt":
                webbrowser.open(f"https://github.com/microsoft/git/releases/download/v{pbconfig.get('supported_git_version')}/Git-{pbconfig.get('supported_git_version')}-64-bit.exe")
            needs_git_update = True


        if os.name == "nt":
            # find Git/cmd/git.exe
            git_paths = [path for path in pbtools.whereis("git") if "cmd" in path.parts]

            if len(git_paths) > 0:
                bundled_git_lfs = False

                is_admin = pbuac.isUserAdmin()

                delete_paths = []

                for git_path in git_paths:
                    # find Git from Git/cmd/git.exe
                    git_root = git_path.parents[1]
                    possible_lfs_paths = ["cmd/git-lfs.exe", "mingw64/bin/git-lfs.exe", "mingw64/libexec/git-core/git-lfs.exe"]
                    for possible_lfs_path in possible_lfs_paths:
                        path = git_root / possible_lfs_path
                        if path.exists():
                            try:
                                if is_admin:
                                    path.unlink()
                                else:
                                    delete_paths.append(str(path))
                            except FileNotFoundError:
                                pass
                            except OSError:
                                pblog.error(f"Git LFS is bundled with Git, overriding your installed version. Please remove {path}.")
                                bundled_git_lfs = True

                if not is_admin and len(delete_paths) > 0:
                    pblog.info("Requesting permission to delete bundled Git LFS which is overriding your installed version...")
                    quoted_paths = [f'"{path}"' for path in delete_paths]
                    delete_cmdline = ["cmd.exe",  "/c", "DEL", "/q", "/f"] + quoted_paths
                    try:
                        ret = pbuac.runAsAdmin(delete_cmdline)
                    except OSError:
                        pblog.error("User declined permission. Automatic delete failed.")

                for delete_path in delete_paths:
                    path = pathlib.Path(delete_path)
                    if path.exists():
                        bundled_git_lfs = True
                        pblog.error(f"Git LFS is bundled with Git, overriding your installed version. Please remove {path}.")

                if bundled_git_lfs:
                    pbtools.error_state()

        detected_lfs_version = pbgit.get_lfs_version()
        if detected_lfs_version == pbconfig.get('supported_lfs_version'):
            pblog.info(f"Current Git LFS version: {detected_lfs_version}")
        else:
            pblog.error("Git LFS is not updated to the supported version in your system")
            pblog.error(f"Supported Git LFS Version: {pbconfig.get('supported_lfs_version')}")
            pblog.error(f"Current Git LFS Version: {detected_lfs_version}")
            pblog.error("Please install the supported Git LFS version from https://git-lfs.github.com")
            if os.name == "nt":
                supported_lfs_version = pbconfig.get('supported_lfs_version').split("/")[1]
                webbrowser.open(f"https://github.com/git-lfs/git-lfs/releases/download/v{supported_lfs_version}/git-lfs-windows-v{supported_lfs_version}.exe")
            needs_git_update = True

        if needs_git_update:
            pbtools.error_state()

        pblog.info("------------------")

        # Do not execute if Unreal Editor is running
        if pbtools.get_running_process("UE4Editor") is not None:
            pbtools.error_state("Unreal Editor is currently running. Please close it before running PBSync. It may be listed only in Task Manager as a background process. As a last resort, you should log off and log in again.")

        current_branch = pbgit.get_current_branch_name()
        # repo was already fetched in StartProject.bat
        if current_branch != "promoted":
            pblog.info("Fetching recent changes on the repository...")
            fetch_base = ["git", "fetch", "origin"]
            branches = {"promoted", "master", "trunk", current_branch}
            fetch_base.extend(branches)
            pbtools.get_combined_output(fetch_base)

        # Do some housekeeping for git configuration
        pbgit.setup_config()

        # Check if we have correct credentials
        pbgit.check_credentials()

        pblog.info("------------------")

        # Execute synchronization part of script if we're on the expected branch, or force sync is enabled
        is_on_expected_branch = pbgit.compare_with_current_branch_name(pbconfig.get('expected_branch_name'))
        if sync_val == "force" or is_on_expected_branch:
            pbtools.resolve_conflicts_and_pull()

            pblog.info("------------------")

            project_version = pbunreal.get_project_version()
            if project_version is not None:
                pblog.info(f"Current project version: {project_version}")
            else:
                pbtools.error_state(
                    "Something went wrong while fetching project version. Please request help in #tech-support.")

            if pbhub.is_pull_binaries_required():
                pblog.info("Binaries are not up to date, trying to pull new binaries...")
                ret = pbhub.pull_binaries(project_version)
                if ret == 0:
                    pblog.info("Binaries were pulled successfully")
                elif ret < 0:
                    pbtools.error_state("Binaries pull failed, please view log for instructions.")
                elif ret > 0:
                    pbtools.error_state("An error occurred while pulling binaries. Please request help in #tech-support to resolve it, and please do not run StartProject.bat until the issue is resolved.", True)
            else:
                pblog.info("Binaries are up-to-date")
        else:
            pblog.warning(f"Current branch is not supported for repository synchronization: {pbgit.get_current_branch_name()}. Auto synchronization "
                          "will be disabled")

        pblog.info("------------------")

        pblog.info("Checking for engine updates...")
        if pbgit.sync_file("ProjectBorealis.uproject") != 0:
            pbtools.error_state(
                "Something went wrong while updating the .uproject file. Please request help in #tech-support.")

        engine_version = pbunreal.get_engine_version(False)

        pblog.info("Trying to register current engine build if it exists. Otherwise, the build will be downloaded...")

        symbols_needed = pbunreal.is_versionator_symbols_enabled()
        bundle_name = pbconfig.get("ue4v_default_bundle")

        if pbunreal.run_ue4versionator(bundle_name, symbols_needed) != 0:
            pblog.error(f"Something went wrong while registering engine build {bundle_name}-{engine_version}. Please request help in #tech-support.")
            sys.exit(1)
        else:
            pblog.info(f"Engine build {bundle_name}-{engine_version} successfully registered")

        # Clean old engine installations, do that only in expected branch
        if is_on_expected_branch:
            if pbunreal.clean_old_engine_installations():
                pblog.info("Old engine installations are successfully cleaned")
            else:
                pblog.warning("Something went wrong while cleaning old engine installations. You may want to clean them manually.")

        pblog.info("------------------")

        if pbunreal.check_ue4_file_association():
            try:
                os.startfile(os.path.normpath(os.path.join(os.getcwd(), "ProjectBorealis.uproject")))
            except NotImplementedError:
                pblog.info("You may now launch ProjectBorealis.uproject with Unreal Engine 4.")
        else:
            pbtools.error_state(".uproject extension is not correctly set into Unreal Engine. Make sure you have Epic Games Launcher installed. If problem still persists, please get help in #tech-support.")

    elif sync_val == "engineversion":
        if repository_val is None:
            pblog.error("--repository <URL> argument should be provided with --sync engine command")
            sys.exit(1)
        engine_version = pbunreal.get_latest_available_engine_version(str(repository_val))
        if engine_version is None:
            pblog.error("Error while trying to fetch latest engine version")
            sys.exit(1)
        if not pbunreal.set_engine_version(engine_version):
            pblog.error("Error while trying to update engine version in .uproject file")
            sys.exit(1)
        pblog.info(f"Successfully changed engine version as {str(engine_version)}")

    elif sync_val == "ddc":
        pbunreal.generate_ddc_data()

    elif sync_val == "binaries":
        project_version = pbunreal.get_project_version()
        ret = pbhub.pull_binaries(project_version, True)
        if ret == 0:
            pblog.info(f"Binaries for {project_version} pulled & extracted successfully")
        else:
            pblog.error(f"Failed to pull binaries for {project_version}")
            sys.exit(1)

    elif sync_val == "engine":
        # Pull engine build with ue4versionator & register it
        if requested_bundle_name is None:
            requested_bundle_name = pbconfig.get("ue4v_default_bundle")

        engine_version = pbunreal.get_engine_version(False)
        if pbunreal.run_ue4versionator(requested_bundle_name) != 0:
            pblog.error(f"Something went wrong while registering engine build {requested_bundle_name}-{engine_version}")
            sys.exit(1)
        else:
            pblog.info(f"Engine build {requested_bundle_name}-{engine_version} successfully registered")


def clean_handler(clean_val):
    if clean_val == "workspace":
        if pbtools.wipe_workspace():
            pblog.info("Workspace wipe successful")
        else:
            pblog.error("Something went wrong while wiping the workspace")
            sys.exit(1)

    elif clean_val == "engine":
        if not pbunreal.clean_old_engine_installations():
            pblog.error(
                "Something went wrong while cleaning old engine installations. You may want to clean them manually.")
            sys.exit(1)


def printversion_handler(print_val, repository_val=None):
    if print_val == "latest-engine":
        if repository_val is None:
            pblog.error("--repository <URL> argument should be provided with --print latest-engine command")
            sys.exit(1)
        engine_version = pbunreal.get_latest_available_engine_version(str(repository_val))
        if engine_version is None:
            sys.exit(1)
        print(engine_version, end="")

    elif print_val == "current-engine":
        engine_version = pbunreal.get_engine_version()
        if engine_version is None:
            sys.exit(1)
        print(engine_version, end="")

    elif print_val == "project":
        project_version = pbunreal.get_project_version()
        if project_version is None:
            sys.exit(1)
        print(project_version, end="")


def autoversion_handler(autoversion_val):
    if pbunreal.project_version_increase(autoversion_val):
        pblog.info("Successfully increased project version")
    else:
        pblog.error("Error occurred while trying to increase project version")
        sys.exit(1)


def publish_handler(publish_val, dispatch_exec_path):
    if dispatch_exec_path is None:
        pblog.error(
            "--dispatch argument should be provided for --publish command")
        sys.exit(1)

    if not pbdispatch.push_build(publish_val, dispatch_exec_path, pbconfig.get('dispatch_config'), pbconfig.get('dispatch_stagedir'), pbconfig.get('dispatch_drm')):
        pblog.error("Something went wrong while pushing a new playable build.")
        sys.exit(1)


def push_handler(file_name):
    project_version = pbunreal.get_project_version()
    pblog.info(f"Attaching {file_name} into GitHub release {project_version}")
    if not pbhub.push_package(project_version, file_name):
        pblog.error(f"Error occurred while pushing package for release {project_version}")
        sys.exit(1)


def main(argv):
    parser = argparse.ArgumentParser(description=f"Project Borealis Workspace Synchronization Tool | PBpy Library Version: {pbpy_version.ver} | PBSync Program Version: {pbsync_version.ver}")

    parser.add_argument("--sync", help="Main command for the PBSync, synchronizes the project with latest changes from the repo, and does some housekeeping",
                        choices=["all", "binaries", "engineversion", "engine", "force", "ddc"])
    parser.add_argument("--printversion", help="Prints requested version information into console. latest-engine command needs --repository parameter",
                        choices=["current-engine", "latest-engine", "project"])
    parser.add_argument(
        "--repository", help="Required gcloud repository url for --printversion latest-engine and --sync engine commands")
    parser.add_argument("--autoversion", help="Automatic version update for project version",
                        choices=["hotfix", "stable", "public"])
    parser.add_argument("--clean", help="""Do cleanup according to specified argument. If engine is provided, old engine installations will be cleared
    If workspace is provided, workspace will be reset with latest changes from current branch (not revertible)""", choices=["engine", "workspace"])
    parser.add_argument("--config", help=f"Path of config XML file. If not provided, ./{default_config_name} is used as default", default=default_config_name)
    parser.add_argument(
        "--push", help="Push provided file into release of current project version")
    parser.add_argument("--publish", help="Publishes a playable build with provided build type",
                        choices=["internal", "playtester"])
    parser.add_argument(
        "--dispatch", help="Required dispatch executable path for --publish command")
    parser.add_argument(
        "--bundle", help="Engine bundle name for --sync engine command. If not provided, ue4versionator will use the default bundle supplied by the config file")
    parser.add_argument(
        "--debugpath", help="If provided, PBSync will run in provided path")
    parser.add_argument(
        "--debugbranch", help="If provided, PBSync will use provided branch as expected branch")

    if len(argv) > 0:
        args = parser.parse_args(argv)
    else:
        pblog.error("At least one valid argument should be passed!")
        pblog.error("Did you mean to launch StartProject.bat?")
        input("Press enter to continue...")
        sys.exit(1)

    if not (args.debugpath is None):
        # Work on provided debug path
        os.chdir(str(args.debugpath))

    # Parser function object for PBSync config file
    def pbsync_config_parser_func(root): return {
        'supported_git_version': root.find('git/version').text,
        'supported_lfs_version': root.find('git/lfsversion').text,
        'expected_branch_name': root.find('git/expectedbranch').text if args.debugbranch is None else str(args.debugbranch),
        'lfs_lock_url': root.find('git/lfslockurl').text,
        'git_url': root.find('git/url').text,
        'checksum_file': root.find('git/checksumfile').text,
        'log_file_path': root.find('log/file').text,
        'ue4v_user_config': root.find('versionator/userconfig').text,
        'ue4v_ci_config': root.find('versionator/ciconfig').text,
        'ue4v_default_bundle': root.find('versionator/defaultbundle').text,
        'ue4v_ci_bundle': root.find('versionator/cibundle').text,
        'engine_base_version': root.find('project/enginebaseversion').text,
        'uproject_name': root.find('project/uprojectname').text,
        'defaultgame_path': root.find('project/defaultgameinipath').text,
        'dispatch_config': root.find('dispatch/config').text,
        'dispatch_drm': root.find('dispatch/drm').text,
        'dispatch_stagedir': root.find('dispatch/stagedir').text
    }

    # Preparation
    config_handler(args.config, pbsync_config_parser_func)
    pblog.setup_logger(pbconfig.get('log_file_path'))

    # Do not process further if we're in an error state
    if pbtools.check_error_state():
        pbtools.error_state(f"""Repository is currently in an error state. Please fix the issues in your workspace 
        before running PBSync.\nIf you have already fixed the problem, you may remove {pbtools.error_file} from your project folder & 
        run StartProject bat file again.""", True)

    # Parse args
    if not (args.sync is None):
        sync_handler(args.sync, args.repository, args.bundle)
    elif not (args.printversion is None):
        printversion_handler(args.printversion, args.repository)
    elif not (args.autoversion is None):
        autoversion_handler(args.autoversion)
    elif not (args.clean is None):
        clean_handler(args.clean)
    elif not (args.publish is None):
        publish_handler(args.publish, args.dispatch)
    elif not (args.push is None):
        push_handler(args.push)
    else:
        pblog.error("At least one valid argument should be passed!")
        pblog.error("Did you mean to launch StartProject.bat?")
        input("Press enter to continue...")
        sys.exit(1)


if __name__ == '__main__':
    if "Scripts" in os.getcwd():
        # Working directory fix for scripts calling PBSync from Scripts folder
        os.chdir("..")
    main(sys.argv[1:])
